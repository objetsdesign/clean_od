import json
import logging
import os
import shutil
import subprocess
import tempfile
import odoo
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import find_pg_tool, exec_pg_environ
from odoo.service import db

_logger = logging.getLogger(__name__)


class DbBackupConfigure(models.Model):
    _name = 'db.backup.configure'
    _description = 'Automatic Database Backup'

    name = fields.Char(string='Name', required=True, help='Add the name')
    db_name = fields.Char(string='Database Name', required=True,
                          help='Name of the database')
    master_pwd = fields.Char(string='Master Password', required=True,
                             help='Master password')
    backup_format = fields.Selection([
        ('zip', 'Zip'),
        ('dump', 'Dump')
    ], string='Backup Format', default='zip', required=True,
        help='Format of the backup')
    backup_frequency = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ], default='daily', string='Backup Frequency', help='Frequency of Backup Scheduling')
    backup_path = fields.Char(string='Backup Path',
                              help='Local storage directory path' , default=lambda self: os.getcwd() , required=True)

    backup_time = fields.Datetime(string='Backup Time', help='Date and Time for cron job to trigger')

    active = fields.Boolean(default=False, string='Active',
                            help='Activate the Scheduled Action or not')
    auto_remove = fields.Boolean(string='Remove Old Backups',
                                 help='Remove old backups')
    days_to_remove = fields.Integer(string='Remove After',
                                    help='Automatically delete stored backups'
                                         ' after this specified number of days')
    notify_user = fields.Boolean(string='Notify User',
                                 help='Send an email notification to user when'
                                      'the backup operation is successful'
                                      'or failed')
    user_id = fields.Many2one('res.users', string='User',
                              help='Name of the user')
    backup_filename = fields.Char(string='Backup Filename',
                                  help='For Storing generated backup filename')


    @api.constrains('db_name')
    def _check_db_credentials(self):
        """Validate entered database name and master password"""
        database_list = db.list_dbs(force=True)
        if self.db_name not in database_list:
            raise ValidationError(_("Invalid Database Name!"))
        try:
            odoo.service.db.check_super(self.master_pwd)
        except Exception:
            raise ValidationError(_("Invalid Master Password!"))
        

    @api.onchange('backup_time')
    def _onchange_backup_time(self):
        """Update the cron job nextcall timing based on the backup_time."""
        if self.backup_time:
            # Ensure backup_time is a future time

            cron_id = ''
            if self.backup_frequency == 'daily':
                cron_id = 'Backup : Daily Database Backup'
            elif self.backup_frequency == 'weekly':
                cron_id = 'Backup : Weekly Database Backup'
            elif self.backup_frequency == 'monthly':
                cron_id = 'Backup : Monthly Database Backup'

            # Now we try to find the correct cron job based on frequency using search
            cron = self.env['ir.cron'].search([('name', '=', cron_id)], limit=1)
            if cron:
                # Update the cron job's nextcall field with the new backup_time
                cron.write({
                    'nextcall': self.backup_time,
                })
                _logger.info('Cron job nextcall updated to: %s', self.backup_time)
            else:
                _logger.warning('Cron job not found to update.')


    def _schedule_auto_backup(self, frequency):
        """Function for generating and storing backup.
           Database backup for all the active records in backup configuration
           model will be created."""
        if frequency == 'backup_now':
            records = self.search([('active', '=', True)])
        else:
            records = self.search([('backup_frequency', '=', frequency), ('active', '=', True)])
        mail_template_success = self.env.ref(
            'auto_database_backup_odoo.mail_template_data_db_backup_successful')
        mail_template_failed = self.env.ref(
            'auto_database_backup_odoo.mail_template_data_db_backup_failed')
        for rec in records:
            backup_time = fields.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
            backup_filename = f"{rec.db_name}_{backup_time}.{rec.backup_format}"
            rec.backup_filename = backup_filename
            try:
                if not os.path.isdir(rec.backup_path):
                    os.makedirs(rec.backup_path)
                backup_file = os.path.join(rec.backup_path,
                                            backup_filename)
                f = open(backup_file, "wb")
                self.dump_data(rec.db_name, f, rec.backup_format, frequency)
                f.close()

                with open(backup_file, "rb") as bf:
                    file_data = bf.read()
                self.env["db.backup.history"].create({
                    "name": backup_filename,
                    "backup_path": backup_file,
                    "backup_path": backup_file,
                    "backup_date": fields.Datetime.now(),  # Odoo safe datetime
                    # "backup_file": base64.b64encode(file_data),
                })
                # Remove older backups
                if rec.auto_remove:
                    for filename in os.listdir(rec.backup_path):
                        file = os.path.join(rec.backup_path, filename)
                        if os.path.isfile(file):
                            create_time = fields.datetime.fromtimestamp(
                                os.path.getctime(file))
                            backup_duration = fields.datetime.utcnow() - create_time
                            if backup_duration.days >= rec.days_to_remove:
                                os.remove(file)
                if rec.notify_user:
                    mail_template_success.send_mail(rec.id, force_send=True)
            except Exception as e:
                rec.generated_exception = e
                _logger.info('FTP Exception: %s', e)
                if rec.notify_user:
                    mail_template_failed.send_mail(rec.id, force_send=True)
                raise ValidationError(_("Invalid Master Password! %s") % e)

    def dump_data(self, db_name, stream, backup_format, backup_frequency):
        """Dump database `db` into file-like object `stream` if stream is None
        return a file object with the dump. """
         # Bypass cron job check if the frequency is 'backup_now' (i.e., triggered manually via the button)
        if backup_frequency != 'backup_now':
            cron_user_id = self.env.ref(f'auto_database_backup_odoo.ir_cron_auto_db_backup_{backup_frequency}').user_id.id
            if cron_user_id != self.env.user.id:
                _logger.error(
                    'Unauthorized database operation. Backups should only be available from the cron job.')
                raise ValidationError("Unauthorized database operation. Backups should only be available from the cron job.")
    
        _logger.info('DUMP DB: %s format %s', db_name, backup_format)
        cmd = [find_pg_tool('pg_dump'), '--no-owner', db_name]
        env = exec_pg_environ()
        if backup_format == 'zip':
            with tempfile.TemporaryDirectory() as dump_dir:
                filestore = odoo.tools.config.filestore(db_name)
                cmd.insert(-1,'--file=' + os.path.join(dump_dir, 'dump.sql'))
                subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.STDOUT, check=True)
                if os.path.exists(filestore):
                    shutil.copytree(filestore,
                                    os.path.join(dump_dir, 'filestore'))
                with open(os.path.join(dump_dir, 'manifest.json'), 'w') as fh:
                    db = odoo.sql_db.db_connect(db_name)
                    with db.cursor() as cr:
                        json.dump(self._dump_db_manifest(cr), fh, indent=4)
                if stream:
                    odoo.tools.osutil.zip_dir(dump_dir, stream,
                                              include_dir=False,
                                              fnct_sort=lambda
                                                  file_name: file_name != 'dump.sql')
                else:
                    t = tempfile.TemporaryFile()
                    odoo.tools.osutil.zip_dir(dump_dir, t, include_dir=False,
                                              fnct_sort=lambda
                                                  file_name: file_name != 'dump.sql')
                    t.seek(0)
                    return t
        else:
            cmd.insert(-1,'--format=c')
            process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
            stdout, _ = process.communicate()
            if stream:
                stream.write(stdout)
            else:
                return stdout

    def _dump_db_manifest(self, cr):
        """ This function generates a manifest dictionary for database dump."""
        pg_version = "%d.%d" % divmod(cr._obj.connection.server_version / 100, 100)
        cr.execute(
            "SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'")
        modules = dict(cr.fetchall())
        manifest = {
            'odoo_dump': '1',
            'db_name': cr.dbname,
            'version': odoo.release.version,
            'version_info': odoo.release.version_info,
            'major_version': odoo.release.major_version,
            'pg_version': pg_version,
            'modules': modules,
        }
        return manifest


    def action_trigger_immediate_backup(self):
        """Method to trigger immediate backup for multiple records"""
        for record in self:
            record._schedule_auto_backup('backup_now')

