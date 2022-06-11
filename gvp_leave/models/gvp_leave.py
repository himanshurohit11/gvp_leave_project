from odoo import api, fields, models, _
from odoo.exceptions import UserError,ValidationError
from dateutil.relativedelta import relativedelta

class GvpLeave(models.Model):
    _inherit = 'hr.leave.type'

    check_child = fields.Boolean()
    many_responsible = fields.Selection([('any', 'Any'),('all', 'All'),], default='all', index=True, required=True)
    leave_validation_type = fields.Selection(selection_add=[('committee','Committe For Approval')])
    responsible_ids = fields.Many2many(
        'res.users',
        domain=lambda self: [('groups_id', 'in', self.env.ref('hr_holidays.group_hr_holidays_user').id)],
        help="Choose the Time Off Officer who will be notified to approve allocation or Time Off request")
    aprover_count = fields.Integer(string="Approver", compute="_compute_aprover_count", readonly=False, store=True)

    @api.depends('many_responsible', 'responsible_ids')
    def _compute_aprover_count(self):
        for type in self:
            if type.many_responsible == "all":
                type.aprover_count = len(type.responsible_ids)

class HrLeave(models.Model):
    _name = 'hr.leave'
    _inherit = ['hr.leave']

    approved_by = fields.Many2many('res.users', string='Approved By')
    approved_by_count = fields.Integer(string="Approved By Count")
    check_approval = fields.Boolean(compute="compute_check_approve")

    @api.constrains('holiday_status_id')
    def _ckeck_child(self):
        if self.holiday_status_id.check_child:
            if (self.holiday_status_id.check_child and self.employee_ids.children >= 2) or self.employee_ids.count_join_days < 365:
                raise ValidationError('You are not aligible for this leave')

    def _get_responsible_for_approval(self):
        if self.validation_type == 'committee':
            return self.holiday_status_id.responsible_ids
        return super(HrLeave, self)._get_responsible_for_approval()

    def activity_update(self):
        if not self.approved_by:
            if self.validation_type == 'committee':
                user_ids=self.sudo()._get_responsible_for_approval().ids
                for user in user_ids:
                    if self.state == 'confirm':
                        self.activity_schedule('hr_holidays.mail_act_leave_approval', user_id = user)
                return True
        elif self.approved_by:
            if self.state != 'validate1' or self.holiday_status_id.aprover_count >= self.approved_by_count:
                if self.env.user.id in self.holiday_status_id.responsible_ids.ids:
                    self.activity_feedback(['hr_holidays.mail_act_leave_approval'], user_id = self.env.user.id)
            return True
        return super(HrLeave, self).activity_update()

    def action_approve(self):
        if any(holiday.state != 'confirm' for holiday in self):
            raise UserError(_('Time off request must be confirmed ("To Approve") in order to approve it.'))
        current_user = self.env.user
        committee_leave = self.filtered(lambda hol: hol.validation_type == 'committee')
        if committee_leave:
            if current_user in self.sudo()._get_responsible_for_approval():
                committee_leave.approved_by += current_user
                committee_leave.approved_by_count += 1
            if self.holiday_status_id.aprover_count != len(committee_leave.approved_by):
                committee_leave.message_post(
                body=_(
                    'Your %(leave_type)s planned on %(date)s has been accepted',
                    leave_type=committee_leave.holiday_status_id.display_name,
                    date=committee_leave.date_from
                ),
                partner_ids=committee_leave.employee_id.user_id.partner_id.ids)
                committee_leave.activity_update()
            if committee_leave.holiday_status_id.aprover_count == committee_leave.approved_by_count:
                return super(HrLeave, self).action_approve()
        else:
            return super(HrLeave, self).action_approve()

    @api.depends('approved_by')
    def compute_check_approve(self):
        current_user = self.env.user
        for leave in self:
            leave.check_approval = True
            if current_user in leave.approved_by:
                leave.check_approval = False

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    
    date_of_joining = fields.Date(default=fields.Date.context_today)
    retire_date = fields.Date(compute="_set_retirement_date")
    count_join_days = fields.Integer(compute="_compute_count_join_days", store=True)
    
    @api.depends('date_of_joining')
    def _compute_count_join_days(self):
        date_now = fields.Date.from_string(fields.Date.today(self))
        for employee in self:
            joinning_date = fields.Date.from_string(employee.date_of_joining)
            employee.count_join_days = (date_now - joinning_date).days

    @api.depends('birthday')
    def _set_retirement_date(self):
        for record in self:
            if record.birthday:
                record.retire_date = record.birthday + relativedelta(years=60)
            else:
                record.retire_date = False
