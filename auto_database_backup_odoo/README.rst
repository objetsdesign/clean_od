================================================================
Automatic Database Backup To Local Server
================================================================

The Automatic Database Backup To Local Server module for Odoo 18 automates the process of backing up your Odoo database to a local server. This module ensures that your Odoo instance is regularly backed up without manual intervention, making it an essential tool for businesses that want to safeguard their data. With easy configuration and reliable performance, this module simplifies the backup process and minimizes the risk of data loss.

.. role:: raw-html(raw)
:format: html
**Table of contents**

.. contents::
:local:

Installation
================================================================
**To install this, follow below steps:**

* Just simply mount this module as Odoo's custom module

* Now, Install the module in Odoo from **Main Apps** section.

Usage
================================================================

**How to use this module:**

Set Up Automatic Backup

After installing the module, you will need to configure the backup settings:

1. Go to the Backup configuration menu from the automatic database backup.

.. image:: auto_database_backup_odoo/static/src/images/1.png
 :alt: Example Image
 :width: 300px


2. Set up the backup frequency (backup now,daily, weekly, etc.).

.. image:: auto_database_backup_odoo/static/src/images/2.png
 :alt: Example Image
 :width: 300px

 3. Specify the local server's directory path where the backups will be saved.

.. image:: auto_database_backup_odoo/static/src/images/2.png
 :alt: Example Image
 :width: 300px


4. Once configured, the module will automatically perform database backups according to the set schedule.


5. After that, you can able to see the history of backup from the Backup History menu.

.. image:: auto_database_backup_odoo/static/src/images/3.png
 :alt: Example Image
 :width: 300px

Notifications

The module can send notifications when a backup is successfully completed or if there is an error.Notification is through the email to stay updated on the status of your backups.

Change Logs
================================================================
18.0.1.0.0
*****************

* ``Added`` Automatic Database Backup To Local Server
* ``Added`` Backup scheduling options.
* ``Added`` Backup history and restore options.
* ``Added`` Notifications for successful and failed backups.

18.1.0.0.0

*****************

* Fixed Issue with backup scheduling not running correctly on certain server configurations.
* Improved Backup compression to save disk space.
* Updated README file for clarity.

Support

================================================================

`Techinfini Solutions pvt ltd <https://techinfini.in/>`_
