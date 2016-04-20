################################################################################
#         _    ____ ___    ____                    _                _          #
#        / \  / ___|_ _|  / ___| _ __   __ _ _ __ | |__   __ _  ___| | __      #
#       / _ \| |    | |   \___ \| '_ \ / _` | '_ \| '_ \ / _` |/ __| |/ /      #
#      / ___ \ |___ | |    ___) | | | | (_| | |_) | |_) | (_| | (__|   <       #
#     /_/   \_\____|___|  |____/|_| |_|\__,_| .__/|_.__/ \__,_|\___|_|\_\      #
#                                           |_|                                #
#                                                                              #
################################################################################
#                                                                              #
# Copyright (c) 2015 Cisco Systems                                             #
# All Rights Reserved.                                                         #
#                                                                              #
#    Licensed under the Apache License, Version 2.0 (the "License"); you may   #
#    not use this file except in compliance with the License. You may obtain   #
#    a copy of the License at                                                  #
#                                                                              #
#         http://www.apache.org/licenses/LICENSE-2.0                           #
#                                                                              #
#    Unless required by applicable law or agreed to in writing, software       #
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT #
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the  #
#    License for the specific language governing permissions and limitations   #
#    under the License.                                                        #
#                                                                              #
################################################################################
"""  Snapback: Configuration Snapshot and Rollback for ACI fabrics
     This file contains the main GUI for the Snapback tool
"""
import datetime
from aciconfigdb import ConfigDB
from flask import Flask, render_template, session, redirect, url_for
from flask import flash, send_from_directory, request
from flask.ext.sqlalchemy import SQLAlchemy
from requests import Timeout
from flask.ext import admin
from flask.ext.admin import BaseView, AdminIndexView, expose
from flask.ext.admin.actions import action
from flask.ext.admin.contrib.sqla import ModelView
from flask.ext.admin.model.template import macro
from flask.ext.bootstrap import Bootstrap
from flask.ext.wtf import Form, CsrfProtect
from wtforms import StringField, SubmitField, PasswordField, BooleanField
from wtforms import RadioField, IntegerField, TextAreaField, SelectField
from wtforms.fields.html5 import DateField, DateTimeField
from wtforms.validators import Required, IPAddress, NumberRange
from wtforms.validators import ValidationError, Optional
import difflib
import json
import os
from flask import jsonify
from acitoolkit.acitoolkit import Credentials

# Create application
app = Flask(__name__, static_folder='static')

# Cross site replay security
app.config['SECRET_KEY'] = 'Dnit7qz7mfcP0YuelDrF8vLFvk0snhwP'
app.config['CSRF_ENABLED'] = True
csrf = CsrfProtect(app)

bootstrap = Bootstrap(app)

# Create in-memory database
app.config['DATABASE_FILE'] = 'snapshots.sqlite'
app.config['SQLALCHEMY_DATABASE_URI'] = ('sqlite:///' +
                                         app.config['DATABASE_FILE'])
app.config['SQLALCHEMY_ECHO'] = True
db = SQLAlchemy(app)

# Create the ACI Config Database
cdb = ConfigDB()
versions = cdb.get_versions()


# Credentials
class CredentialsForm(Form):
    ipaddr = StringField('APIC IP Address:',
                         validators=[Required(), IPAddress()])
    secure = BooleanField('Use secure connection', validators=[])
    username = StringField('APIC Username:', validators=[Required()])
    password = PasswordField('APIC Password:', validators=[Required()])
    submit = SubmitField('Save')


class ResetForm(Form):
    reset = SubmitField('Reset')


class CancelSchedule(Form):
    cancel = SubmitField('Cancel Schedule')


class DiffView(BaseView):
    def is_visible(self):
        return False

    @expose('/')
    def index(self):
        files = []
        (file1_id, file2_id) = session.get('diff_files')
        file1_obj = Snapshots.query.get(file1_id)
        file2_obj = Snapshots.query.get(file2_id)
        file1 = str(cdb.get_file(file1_obj.filename,
                                 file1_obj.version)).split('\n')
        file2 = str(cdb.get_file(file2_obj.filename,
                                 file2_obj.version)).split('\n')
        diff = difflib.HtmlDiff(wrapcolumn=120)
        table = diff.make_table(file1, file2)
        return self.render('diffview.html', table=table)


class FileView(BaseView):
    def is_visible(self):
        return False

    @expose('/')
    def index(self):
        files = []
        for fileid in session.get('viewfiles'):
            file_obj = Snapshots.query.get(fileid)
            files.append([cdb.get_file(file_obj.filename, file_obj.version),
                          file_obj.filename,
                          file_obj.version])
        return self.render('fileview.html', files=files)


class FeedbackForm(Form):
    category = SelectField('', choices=[('bug', 'Bug'),
                                        ('enhancement', 'Enhancement Request'),
                                        ('question', 'General Question'),
                                        ('comment', 'General Comment')])
    comment = TextAreaField('Comment', validators=[Required()])
    submit = SubmitField('Submit')


class Feedback(BaseView):
    @expose('/')
    def index(self):
        form = FeedbackForm()
        return self.render('feedback.html', form=form)


class About(BaseView):
    @expose('/')
    def index(self):
        return self.render('about.html')


class StackedDiffsForm(Form):
    show = SubmitField('Show versions with no diffs')
    hide = SubmitField('Hide versions with no diffs')
    start_version = SelectField('Start Version')
    end_version = SelectField('End Version')
    daterange = SubmitField('Set Date Range')


class StackedDiffs(BaseView):
    @expose('/')
    def index(self):
        if session.get('hideall') is None:
            session['hideall'] = False
        changes = cdb.get_versions(with_changes=True)
        if changes is None:
            changes = []
        start_choices = []
        end_choices = []
        for choice in changes:
            start_choices.append((choice[0], choice[0]))
            end_choices.append((choice[0], choice[0]))
        if session.get('diffstartversion') is None:
            if len(start_choices):
                session['diffstartversion'] = start_choices[0]
        if session.get('diffendversion') is None:
            if len(end_choices):
                session['diffendversion'] = end_choices[-1]
        MyStackedDiffsForm = type('MyStackedDiffsForm',
                                  (StackedDiffsForm,),
                                  {'start_version': SelectField('Start Version',
                                                                default=session.get('diffstartversion'),
                                                                choices=start_choices),
                                   'end_version': SelectField('End Version',
                                                                default=session.get('diffendversion'),
                                                                choices=end_choices)})
        form = MyStackedDiffsForm()
        f = open('static/data.csv', 'w')
        f.write('Version,Deletions,Additions\n')
        in_range = False
        if session.get('diffstartversion') is None:
            in_range = True
        for (version, additions, deletions) in changes:
            if not in_range and version == session.get('diffstartversion'):
                in_range = True
            if in_range:
                f.write(version + ',' + deletions + ',' + additions + '\n')
            if in_range and version == session.get('diffendversion'):
                in_range = False
        f.close()
        return self.render('stackedbardiffs.html',
                           form=form,
                           hideall=session.get('hideall'))

    @expose('/showhide', methods=['GET', 'POST'])
    def showhide(self):
        #form = StackedDiffsForm()
        if session.get('hideall') is False:
            session['hideall'] = True
        else:
            session['hideall'] = False
        print 'Passing ', session.get('hideall')
        return redirect(url_for('stackeddiffs.index'))

    @expose('/setstartenddiffs', methods=['GET', 'POST'])
    def setstartenddiffs(self):
        session['diffstartversion'] = request.form['start_version']
        session['diffendversion'] = request.form['end_version']
        return redirect(url_for('stackeddiffs.index'))

    @expose('/data.csv')
    def data(self):
        with open('static/data.csv', 'r') as data_file:
            data = data_file.read()
        return data


class ScheduleSnapshotForm(Form):
    frequency = RadioField('Frequency',
                           choices=[('onetime', 'One time'),
                                    ('interval', 'Every')],
                           validators=[Required()],
                           default='onetime')
    number = IntegerField('', validators=[Optional()])
    interval = SelectField('', choices=[('minutes', 'minutes'),
                                        ('hours', 'hours'),
                                        ('days', 'days')])
    date = DateField('Start date', format='%Y-%m-%d',
                     default=datetime.datetime.now)
    time = DateTimeField('Start time', format='%H:%M',
                         default=datetime.datetime.now)
    submit = SubmitField('Schedule Snapshot')

    def validate_number(form, field):
        if form.frequency.data != 'interval':
            raise ValidationError('Should not be set for One time')
        if not isinstance(form.number.data, int) or (form.number.data < 1):
            raise ValidationError('Should be a number greater than 1')


class APICArgs(object):
    def __init__(self, ipaddr, username, secure, password):
        self.login = username
        self.password = password
        if secure:
            self.url = 'https://' + ipaddr
        else:
            self.url = 'http://' + ipaddr


class ScheduleSnapshot(BaseView):
    @expose('/', methods=['GET', 'POST'])
    def index(self):
        form = ScheduleSnapshotForm()
        cancel_form = CancelSchedule()
        if cancel_form.cancel.data:
            cdb.cancel_schedule()
        elif form.validate_on_submit() and form.submit.data:
            # Check if we have APIC Credentials and fail if none.
            if session.get('ipaddr') is None:
                flash('APIC Credentials have not been entered', 'error')
                return self.render('snapshot.html', form=form,
                                   cancel_form=cancel_form,
                                   lastsnapshot=cdb.get_latest_snapshot_time(),
                                   nextsnapshot=cdb.get_next_snapshot_time(),
                                   schedule=cdb.get_current_schedule())
            args = APICArgs(session.get('ipaddr'),
                            session.get('username'),
                            session.get('secure'),
                            session.get('password'))
            # Login (Always do this since multiple login doesn't hurt and
            # this will automatically cover when credentials change)
            try:
                resp = cdb.login(args)
                if resp.ok is not True:
                    flash('Unable to login to the APIC', 'error')
                    return self.render('snapshot.html', form=form,
                                       cancel_form=cancel_form,
                                       lastsnapshot=cdb.get_latest_snapshot_time(),
                                       nextsnapshot=cdb.get_next_snapshot_time(),
                                       schedule=cdb.get_current_schedule())
            except Timeout:
                flash('Connection timeout when trying to reach the APIC',
                      'error')
                return self.render('snapshot.html', form=form,
                                   cancel_form=cancel_form,
                                   lastsnapshot=cdb.get_latest_snapshot_time(),
                                   nextsnapshot=cdb.get_next_snapshot_time(),
                                   schedule=cdb.get_current_schedule())

            date = form.date.data
            time = form.time.data
            start = datetime.datetime(date.year, date.month, date.day,
                                      time.hour, time.minute)
            # Take a snapshot
            cdb.schedule_snapshot(form.frequency.data,
                                  form.number.data,
                                  form.interval.data,
                                  form.date.data,
                                  form.time.data,
                                  build_db)

            flash('Snapshot successfully scheduled', 'success')
            return redirect(url_for('schedulesnapshot.index'))
        return self.render('snapshot.html', form=form,
                           cancel_form=cancel_form,
                           lastsnapshot=cdb.get_latest_snapshot_time(),
                           nextsnapshot=cdb.get_next_snapshot_time(),
                           schedule=cdb.get_current_schedule())
        
class JsonInterface(BaseView): 
    @csrf.exempt
    @app.route('/login', methods=['POST'])
    def login():
        if request.method == 'POST':
            data = request.json
            session['ipaddr'] = data['ipaddr']
            session['secure'] = data['secure']
            session['username'] = data['username']
            session['password'] = data['password']
            if (session.get('ipaddr') is None or session.get('username') is None or session.get('password') is None):
                return "please provide ipaddress, username,password"
            
            args = APICArgs(session.get('ipaddr'),
                           session.get('username'),
                           session.get('secure'),
                           session.get('password'))
            try:
                resp = cdb.login(args)
                if resp.ok is not True:
                    return 'Unable to login to the APIC'
            except Timeout:
                return 'Connection timeout when trying to reach the APIC'
        return 'loged in'
        '''
        method to login to aci config db
        usage : curl -H "Content-Type: application/json" -X POST http://127.0.0.1:5000/login --data @login.json
        and the login.json structrue is
        {"ipaddr":"","secure":"","username":"","password":""}
        '''

    @csrf.exempt
    @app.route('/viewsnapshots', methods=['POST'])
    def viewsnapshots():
        if request.method == 'POST':
            versions = cdb.get_versions(with_changes=True)
            data = {}
            Items = []
            for (version, additions, deletions) in versions:
                for (filename, adds, dels) in cdb.get_filenames(version,
                                                        prev_version=None,
                                                        with_changes=True):
                    item = {}
                    item['filename'] = filename
                    item['version'] = version
                    Items.append(item)
                    data['items'] = Items
            if request.data != None :
                with open(request.data, 'w') as txtfile:
                    json.dump(data, txtfile)
            return jsonify(data=data)  
            '''
            this method is used to view all the snapshots and write it to a file in json format
            usage : curl -H "Content-Type: application/json" -X POST http://127.0.0.1:5000/viewsnapshots --data "filename"
            '''
    @csrf.exempt
    @app.route('/viewfile', methods=['POST'])
    def viewfile():
        if request.method == 'POST':
            files = []
            data = request.json
            version_needed = data['version']
            name  = data['name']
            return cdb.get_file(name, version_needed)
        '''
        this method is used to view a single snapshot given name and version in json format
        usgae: curl -H "Content-Type: application/json" -X POST http://127.0.0.1:5000/viewfile -d '{"name":"snapshot_172.31.216.100_14.json","version":"2016-04-01_10.56.57"}'
        displays the json content on terminal
        '''
    @csrf.exempt
    @app.route('/logout')
    def logout():
        if cdb.is_logged_in():
            session['ipaddr'] = None
            session['secure'] = None
            session['username'] = None
            session['password'] = None
            return 'logged out'
        else:
            return 'logged out'
        '''
        this method is used to logout. clears all session variables.
        usage: curl -H "Content-Type: application/json" -X POST http://127.0.0.1:5000/logout
        '''
    @app.route('/cancelschedule', methods=['POST'])
    def canselschedule():
        if request.method == 'POST':
            resp = cdb.cancel_schedule
            return 'cansel schedule successfull'
        '''
        this method is used to cansel the latest scheduled snapshots
        usage: curl -H "Content-Type: application/json" -X POST http://127.0.0.1:5000/cancelschedule
        '''
    @csrf.exempt
    @app.route('/schedulesnapshot', methods=['POST'])
    def schedulesnapshot():
       if request.method == 'POST':
            data = request.json
            if cdb.is_logged_in():
                if data.has_key('date'):
                    date = datetime.datetime.strptime(data['date'], '%b %d %Y')
                else:
                    date = datetime.date.today()
                if data.has_key('starttime'):
                    starttime = datetime.datetime.strptime(data['starttime'], '%I:%M%p')
                else:
                    starttime = datetime.datetime.now()
                if data.has_key("frequency") or data['frequency'] is "onetime" or data['frequency'] is "interval":
                    if data['interval'] is "minutes" or data['interval'] is "hours" or data['interval'] is "days" :
                        resp = cdb.schedule_snapshot(data['frequency'],
                                  data['number'],
                                  data['interval'],
                                  date,
                                  starttime,
                                  build_db)
                        if resp.ok is not True:
                            return 'schedule failed'
                return "Snapshot successfully scheduled\n"
            else:
                return 'please login'
            '''
            this method is used to schedule snapshots.
            usage : curl -H "Content-Type: application/json" -X POST http://127.0.0.1:5000/schedulesnapshot --data @sample.json
            and the sample.json structure is 
            {"frequency":"onetime","date":"Jun 1 2005","starttime":"1:33PM","number":"","interval":"minutes"}
            interval supports minutes , hours, days
            frequency supports onetime and ongoing
            '''

class CredentialsView(BaseView):
    @expose('/', methods=['GET', 'POST'])
    def index(self):
        form = CredentialsForm()
        reset_form = ResetForm()
        if form.validate_on_submit() and form.submit.data:
            old_ipaddr = session.get('ipaddr')
            old_username = session.get('username')
            old_secure = session.get('secure')
            old_password = session.get('password')
            if ((old_ipaddr is not None and old_ipaddr != form.ipaddr.data) or
                (old_username is not None and old_username != form.username.data) or
                (old_secure is not None and old_secure != form.secure.data) or
                (old_password is not None and old_password != form.password.data)):
                flash('APIC Credentials have been updated')
            session['ipaddr'] = form.ipaddr.data
            session['secure'] = form.secure.data
            session['username'] = form.username.data
            session['password'] = form.password.data
            return redirect(url_for('credentialsview.index'))
        elif reset_form.reset.data:
            session['ipaddr'] = None
            session['secure'] = None
            session['username'] = None
            session['password'] = None
            return redirect(url_for('credentialsview.index'))
        return self.render('credentials.html', form=form,
                           reset_form=reset_form,
                           ipaddr=session.get('ipaddr'),
                           username=session.get('username'))


# Models
class Snapshots(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Unicode(64))
    filename = db.Column(db.Unicode(64))
    changes = db.Column(db.Unicode(64))
    latest = db.Column(db.Boolean())

    def __unicode__(self):
        return self.version


# Customized admin interface
class CustomView(ModelView):
    list_template = 'list.html'


class SnapshotsAdmin(CustomView):
    can_create = False
    can_edit = False
    column_searchable_list = ('version', 'filename')
    column_filters = ('version', 'filename', 'latest')
    column_formatters = dict(changes=macro('render_changes'))

    # @action('rollback', 'Rollback',
    #         'Are you sure you want to rollback the configuration ?')
    # def rollback(*args, **kwargs):
    #     if session.get('ipaddr') is None:
    #         flash('APIC Credentials have not been entered', 'error')
    #         return redirect(url_for('snapshotsadmin.index_view'))
    #     login_args = APICArgs(session.get('ipaddr'),
    #                           session.get('username'),
    #                           session.get('secure'),
    #                           session.get('password'))
    #     try:
    #         resp = cdb.login(login_args)
    #         if resp.ok is not True:
    #             flash('Unable to login to the APIC', 'error')
    #             return redirect(url_for('snapshotsadmin.index_view'))
    #     except Timeout:
    #         flash('Connection timeout when trying to reach the APIC', 'error')
    #         return redirect(url_for('snapshotsadmin.index_view'))
    #
    #     rollback_files = {}
    #     for file_id in args[1]:
    #         file_obj = Snapshots.query.get(file_id)
    #         version = file_obj.version
    #         if version not in rollback_files:
    #             rollback_files[version] = []
    #         rollback_files[version].append(file_obj.filename)
    #     for version in rollback_files:
    #         cdb.rollback(version, rollback_files[version])
    #     flash(('APIC has been successfully rolled back to the specified'
    #            ' version'), 'success')
    #     return redirect(url_for('snapshotsadmin.index_view'))

    @action('view_diffs', 'View Diffs')
    def view_diffs(*args, **kwargs):
        if len(args[1]) != 2:
            if len(args[1]) > 2:
                flash('Please select only 2 snapshots to view diffs')
            else:
                flash('Please select 2 snapshots to view diffs')
        else:
            session['diff_files'] = args[1]
            return redirect(url_for('diffview.index'))

    @action('view', 'View')
    def view(*args, **kwargs):
        for arg in args[1]:
            obj = Snapshots.query.get(arg)
        session['viewfiles'] = args[1]
        return redirect(url_for('fileview.index'))


class RollbackForm(Form):
    version = SelectField('Version', coerce=int)
    rollback = SubmitField('Rollback')

class RollbackView(BaseView):
    @expose('/', methods=['GET', 'POST'])
    def index(self):
        if session.get('ipaddr') is None:
            flash('APIC Credentials have not been entered', 'error')
            return redirect(url_for('rollbackview.index'))
        args = APICArgs(session.get('ipaddr'),
                        session.get('username'),
                        session.get('secure'),
                        session.get('password'))
        # Login (Always do this since multiple login doesn't hurt and
        # this will automatically cover when credentials change)
        try:
            resp = cdb.login(args)
            if resp.ok is not True:
                flash('Unable to login to the APIC', 'error')
                return redirect(url_for('rollbackview.index'))
        except Timeout:
            flash('Connection timeout when trying to reach the APIC',
                  'error')
            return redirect(url_for('rollbackview.index'))
        form = RollbackForm()
        versions = cdb.get_versions(with_changes=True)
        rollback_versions = []
        if versions is not None:
            count = 0
            for version in versions:
                count += 1
                rollback_versions.append((count, version[0]))
        form.version.choices = rollback_versions
        if form.validate_on_submit() and form.rollback.data:
            version = rollback_versions[form.version.data - 1][1]
            cdb.rollback_using_import_policy(version)
            flash('Rollback successfully processed', 'success')
            return redirect(url_for('rollbackview.index'))
        return self.render('rollback.html', form=form, versions=[])


# Create admin with custom base template
homepage_view = AdminIndexView(name='Home', template='admin/index.html',
                               url='/')
admin = admin.Admin(app,
                    name='Snapback',
                    index_view=homepage_view,
                    base_template='layout.html')

# Add views
admin.add_view(CredentialsView(name='Credentials'))
admin.add_view(ScheduleSnapshot(name='Schedule Snapshot',
                                endpoint='schedulesnapshot'))
admin.add_view(SnapshotsAdmin(Snapshots, db.session,
                              endpoint="snapshotsadmin"))
admin.add_view(RollbackView(name='Version Rollback'))
admin.add_view(StackedDiffs(name='Version Diffs'))
admin.add_view(About(name='About'))
admin.add_view(FileView(name='View'))
admin.add_view(DiffView(name='View Diffs'))
admin.add_view(Feedback(name='Feedback'))


def build_db():
    """
    Populate the db with the existing snapshot images.
    """
    db.drop_all()
    db.create_all()
    prev_version = None
    versions = cdb.get_versions(with_changes=True)
    if versions is None:
        return
    for (version, additions, deletions) in versions:
        for (filename, adds, dels) in cdb.get_filenames(version,
                                                        prev_version=prev_version,
                                                        with_changes=True):
            snapshot = Snapshots()
            snapshot.version = version
            snapshot.filename = filename
            snapshot.changes = adds + '/' + dels
            is_latest = (version == cdb.get_latest_file_version(filename))
            snapshot.latest = is_latest
            db.session.add(snapshot)
        prev_version = version
    db.session.commit()
    return

if __name__ == '__main__':
    description = ('ACI Configuration Snapshot and Rollback tool.')
    creds = Credentials('server', description)
    args = creds.get()

    # Build the database
    build_db()

    # Start app
    app.run(debug=True, host=args.ip, port=int(args.port))
