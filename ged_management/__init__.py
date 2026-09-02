from . import models


def post_init_hook(env):
    """ Crée rétroactivement un dossier GED pour chaque employé et
    chaque projet déjà existants au moment de l'installation du module. """
    employees = env['hr.employee'].search([('ged_folder_id', '=', False)])
    for employee in employees:
        employee._ged_create_folder()

    projects = env['project.project'].search([('ged_folder_id', '=', False)])
    for project in projects:
        project._ged_create_folder()
