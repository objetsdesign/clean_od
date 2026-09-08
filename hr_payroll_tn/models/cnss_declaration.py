# -*- coding: utf-8 -*-
import io
import csv

from odoo import api, fields, models


class HrCnssDeclaration(models.TransientModel):
    _name = 'hr.cnss.declaration'
    _description = "Tableau de bord de télédéclaration CNSS"

    date_from = fields.Date(string="Période du", required=True)
    date_to = fields.Date(string="Au", required=True)
    company_id = fields.Many2one(
        'res.company', default=lambda s: s.env.company, required=True)
    line_ids = fields.One2many(
        'hr.cnss.declaration.line', 'declaration_id', string="Lignes")
    total_base_cnss = fields.Monetary(compute='_compute_totaux', store=True)
    total_cnss_salariale = fields.Monetary(compute='_compute_totaux', store=True)
    total_cnss_patronale = fields.Monetary(compute='_compute_totaux', store=True)
    currency_id = fields.Many2one(
        related='company_id.currency_id', string="Devise")

    @api.depends('line_ids.base_cnss', 'line_ids.cnss_salariale',
                 'line_ids.cnss_patronale')
    def _compute_totaux(self):
        for rec in self:
            rec.total_base_cnss = sum(rec.line_ids.mapped('base_cnss'))
            rec.total_cnss_salariale = sum(
                rec.line_ids.mapped('cnss_salariale'))
            rec.total_cnss_patronale = sum(
                rec.line_ids.mapped('cnss_patronale'))

    def action_generate(self):
        self.ensure_one()
        self.line_ids.unlink()
        payslips = self.env['hr.payslip'].search([
            ('date_from', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
            ('state', 'in', ['done', 'paid']),
            ('company_id', '=', self.company_id.id),
        ])
        lines = []
        for slip in payslips:
            base = sum(slip.line_ids.filtered(
                lambda l: l.code == 'BASECNSS').mapped('total'))
            cot_sal = -sum(slip.line_ids.filtered(
                lambda l: l.code == 'CNSSSAL').mapped('total'))
            cot_pat = sum(slip.line_ids.filtered(
                lambda l: l.code == 'CNSSPAT').mapped('total'))
            lines.append((0, 0, {
                'employee_id': slip.employee_id.id,
                'payslip_id': slip.id,
                'base_cnss': base,
                'cnss_salariale': cot_sal,
                'cnss_patronale': cot_pat,
            }))
        self.line_ids = lines
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.cnss.declaration',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_export_csv(self):
        self.ensure_one()
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=';')
        writer.writerow([
            'Matricule CNSS', 'Employé', 'Base CNSS',
            'CNSS Salariale', 'CNSS Patronale'])
        for line in self.line_ids:
            writer.writerow([
                line.employee_id.cnss_number or '',
                line.employee_id.name,
                '%.3f' % line.base_cnss,
                '%.3f' % line.cnss_salariale,
                '%.3f' % line.cnss_patronale,
            ])
        data = buf.getvalue().encode('utf-8-sig')
        attachment = self.env['ir.attachment'].create({
            'name': 'declaration_cnss_%s_%s.csv' % (
                self.date_from, self.date_to),
            'type': 'binary',
            'datas': __import__('base64').b64encode(data),
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }


class HrCnssDeclarationLine(models.TransientModel):
    _name = 'hr.cnss.declaration.line'
    _description = "Ligne de télédéclaration CNSS"

    declaration_id = fields.Many2one('hr.cnss.declaration', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string="Employé")
    payslip_id = fields.Many2one('hr.payslip', string="Bulletin")
    base_cnss = fields.Monetary(string="Base CNSS")
    cnss_salariale = fields.Monetary(string="CNSS Salariale")
    cnss_patronale = fields.Monetary(string="CNSS Patronale")
    currency_id = fields.Many2one(
        related='declaration_id.currency_id', string="Devise")
