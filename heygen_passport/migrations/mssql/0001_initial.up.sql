-- Heygen Passport initial schema for Microsoft SQL Server.
-- Runs inside the SEPARATE Heygen database (default: HeygenPassport); it
-- never touches any other database. Every table is prefixed hp_.
-- Timestamps are UTC ISO-8601 text (NVARCHAR(40)) and business dates are
-- hotel-local YYYY-MM-DD (NVARCHAR(10)), identical to the SQLite build so the
-- application logic is the same on both engines.

CREATE TABLE hp_settings (
    [key]       NVARCHAR(100) NOT NULL PRIMARY KEY,
    value       NVARCHAR(1000) NOT NULL,
    updated_by  INT NULL,
    updated_at  NVARCHAR(40) NOT NULL
);

CREATE TABLE hp_departments (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    code        NVARCHAR(20) NOT NULL UNIQUE,
    name        NVARCHAR(80) NOT NULL,
    active      INT NOT NULL DEFAULT 1,
    created_at  NVARCHAR(40) NOT NULL
);

CREATE TABLE hp_outlets (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    department_id  INT NULL REFERENCES hp_departments(id),
    name           NVARCHAR(80) NOT NULL,
    active         INT NOT NULL DEFAULT 1,
    created_at     NVARCHAR(40) NOT NULL,
    CONSTRAINT uq_hp_outlets UNIQUE (department_id, name)
);

CREATE TABLE hp_evidence (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    filename     NVARCHAR(200) NOT NULL,
    mime_type    NVARCHAR(100) NOT NULL,
    size_bytes   INT NOT NULL,
    data         VARBINARY(MAX) NOT NULL,
    uploaded_by  INT NULL,
    uploaded_at  NVARCHAR(40) NOT NULL
);

CREATE TABLE hp_staff (
    id                   INT IDENTITY(1,1) PRIMARY KEY,
    employee_id          NVARCHAR(30) NOT NULL UNIQUE,
    full_name            NVARCHAR(120) NOT NULL,
    photo_evidence_id    INT NULL REFERENCES hp_evidence(id),
    job_title            NVARCHAR(80) NOT NULL,
    department_id        INT NOT NULL REFERENCES hp_departments(id),
    employment_status    NVARCHAR(20) NOT NULL DEFAULT 'active'
                         CHECK (employment_status IN ('active','on_leave','suspended','terminated')),
    work_phone           NVARCHAR(30) NULL,
    work_email           NVARCHAR(120) NULL,
    start_date           NVARCHAR(10) NULL,
    outlet_id            INT NULL REFERENCES hp_outlets(id),
    supervisor_staff_id  INT NULL REFERENCES hp_staff(id),
    shift_pattern        NVARCHAR(60) NULL,
    notes                NVARCHAR(MAX) NULL,
    is_demo              INT NOT NULL DEFAULT 0,
    created_at           NVARCHAR(40) NOT NULL,
    created_by           INT NULL,
    updated_at           NVARCHAR(40) NULL,
    updated_by           INT NULL
);
CREATE INDEX ix_hp_staff_dept ON hp_staff(department_id, employment_status);
CREATE INDEX ix_hp_staff_name ON hp_staff(full_name);

CREATE TABLE hp_users (
    id                    INT IDENTITY(1,1) PRIMARY KEY,
    username              NVARCHAR(40) COLLATE Latin1_General_CI_AS NOT NULL UNIQUE,
    password_hash         NVARCHAR(200) NOT NULL,
    role                  NVARCHAR(20) NOT NULL CHECK (role IN ('staff','supervisor','manager','admin')),
    staff_id              INT NULL REFERENCES hp_staff(id),
    department_id         INT NULL REFERENCES hp_departments(id),
    can_score             INT NOT NULL DEFAULT 0,
    active                INT NOT NULL DEFAULT 1,
    must_change_password  INT NOT NULL DEFAULT 1,
    failed_attempts       INT NOT NULL DEFAULT 0,
    locked_until          NVARCHAR(40) NULL,
    last_login_at         NVARCHAR(40) NULL,
    is_demo               INT NOT NULL DEFAULT 0,
    created_at            NVARCHAR(40) NOT NULL,
    created_by            INT NULL,
    updated_at            NVARCHAR(40) NULL,
    updated_by            INT NULL
);
-- One login per staff profile; many accounts (managers/admins) have no profile.
CREATE UNIQUE INDEX ux_hp_users_staff ON hp_users(staff_id) WHERE staff_id IS NOT NULL;

CREATE TABLE hp_profile_fields (
    id                INT IDENTITY(1,1) PRIMARY KEY,
    field_key         NVARCHAR(40) NOT NULL UNIQUE,
    label             NVARCHAR(60) NOT NULL,
    field_type        NVARCHAR(10) NOT NULL DEFAULT 'text' CHECK (field_type IN ('text','date','number','yes_no')),
    visible_to_staff  INT NOT NULL DEFAULT 1,
    active            INT NOT NULL DEFAULT 1,
    created_at        NVARCHAR(40) NOT NULL
);

CREATE TABLE hp_staff_field_values (
    staff_id    INT NOT NULL REFERENCES hp_staff(id),
    field_id    INT NOT NULL REFERENCES hp_profile_fields(id),
    value       NVARCHAR(500) NULL,
    updated_at  NVARCHAR(40) NOT NULL,
    updated_by  INT NULL,
    CONSTRAINT pk_hp_staff_field_values PRIMARY KEY (staff_id, field_id)
);

CREATE TABLE hp_certifications (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    staff_id        INT NOT NULL REFERENCES hp_staff(id),
    name            NVARCHAR(120) NOT NULL,
    cert_type       NVARCHAR(40) NOT NULL DEFAULT 'food_safety',
    issuer          NVARCHAR(120) NULL,
    certificate_no  NVARCHAR(60) NULL,
    issue_date      NVARCHAR(10) NULL,
    expiry_date     NVARCHAR(10) NULL,
    evidence_id     INT NULL REFERENCES hp_evidence(id),
    created_at      NVARCHAR(40) NOT NULL,
    created_by      INT NULL,
    updated_at      NVARCHAR(40) NULL,
    updated_by      INT NULL
);
CREATE INDEX ix_hp_cert_expiry ON hp_certifications(expiry_date);
CREATE INDEX ix_hp_cert_staff ON hp_certifications(staff_id);

CREATE TABLE hp_reg_sources (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    title         NVARCHAR(200) NOT NULL,
    authority     NVARCHAR(120) NOT NULL,
    document_ref  NVARCHAR(120) NULL,
    version       NVARCHAR(60) NULL,
    url           NVARCHAR(500) NULL,
    review_date   NVARCHAR(10) NULL,
    notes         NVARCHAR(MAX) NULL,
    active        INT NOT NULL DEFAULT 1,
    created_at    NVARCHAR(40) NOT NULL,
    created_by    INT NULL,
    updated_at    NVARCHAR(40) NULL,
    updated_by    INT NULL
);

CREATE TABLE hp_templates (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    department_id  INT NOT NULL REFERENCES hp_departments(id),
    name           NVARCHAR(120) NOT NULL,
    description    NVARCHAR(MAX) NULL,
    is_starter     INT NOT NULL DEFAULT 0,
    active         INT NOT NULL DEFAULT 1,
    created_at     NVARCHAR(40) NOT NULL,
    created_by     INT NULL,
    updated_at     NVARCHAR(40) NULL,
    updated_by     INT NULL
);

CREATE TABLE hp_template_items (
    id                     INT IDENTITY(1,1) PRIMARY KEY,
    template_id            INT NOT NULL REFERENCES hp_templates(id),
    title                  NVARCHAR(200) NOT NULL,
    instructions           NVARCHAR(MAX) NULL,
    response_type          NVARCHAR(20) NOT NULL CHECK (response_type IN ('yes_no','pass_fail','numeric','text','photo')),
    min_value              FLOAT NULL,
    max_value              FLOAT NULL,
    unit                   NVARCHAR(20) NULL,
    priority               NVARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high')),
    risk_level             NVARCHAR(10) NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low','medium','high','critical')),
    requires_verification  INT NOT NULL DEFAULT 0,
    due_time               NVARCHAR(5) NULL,
    window_minutes         INT NOT NULL DEFAULT 60,
    sort_order             INT NOT NULL DEFAULT 0,
    reg_source_id          INT NULL REFERENCES hp_reg_sources(id),
    reg_clause             NVARCHAR(200) NULL,
    active                 INT NOT NULL DEFAULT 1,
    created_at             NVARCHAR(40) NOT NULL,
    created_by             INT NULL,
    updated_at             NVARCHAR(40) NULL,
    updated_by             INT NULL
);
CREATE INDEX ix_hp_titem_tpl ON hp_template_items(template_id, active);

CREATE TABLE hp_schedules (
    id                 INT IDENTITY(1,1) PRIMARY KEY,
    template_id        INT NOT NULL REFERENCES hp_templates(id),
    department_id      INT NOT NULL REFERENCES hp_departments(id),
    outlet_id          INT NULL REFERENCES hp_outlets(id),
    job_title          NVARCHAR(80) NULL,
    shift              NVARCHAR(10) NOT NULL DEFAULT 'any' CHECK (shift IN ('any','morning','afternoon','night')),
    assigned_staff_id  INT NULL REFERENCES hp_staff(id),
    start_date         NVARCHAR(10) NOT NULL,
    end_date           NVARCHAR(10) NULL,
    days_of_week       NVARCHAR(20) NOT NULL DEFAULT '0,1,2,3,4,5,6',
    active             INT NOT NULL DEFAULT 1,
    created_at         NVARCHAR(40) NOT NULL,
    created_by         INT NULL,
    updated_at         NVARCHAR(40) NULL,
    updated_by         INT NULL
);
CREATE INDEX ix_hp_sched_dept ON hp_schedules(department_id, active);

CREATE TABLE hp_duties (
    id                     INT IDENTITY(1,1) PRIMARY KEY,
    schedule_id            INT NULL REFERENCES hp_schedules(id),
    template_item_id       INT NULL REFERENCES hp_template_items(id),
    duty_date              NVARCHAR(10) NOT NULL,
    department_id          INT NOT NULL REFERENCES hp_departments(id),
    outlet_id              INT NULL REFERENCES hp_outlets(id),
    job_title              NVARCHAR(80) NULL,
    shift                  NVARCHAR(10) NOT NULL DEFAULT 'any',
    assigned_staff_id      INT NULL REFERENCES hp_staff(id),
    title                  NVARCHAR(200) NOT NULL,
    instructions           NVARCHAR(MAX) NULL,
    response_type          NVARCHAR(20) NOT NULL,
    min_value              FLOAT NULL,
    max_value              FLOAT NULL,
    unit                   NVARCHAR(20) NULL,
    priority               NVARCHAR(10) NOT NULL,
    risk_level             NVARCHAR(10) NOT NULL,
    requires_verification  INT NOT NULL DEFAULT 0,
    due_at                 NVARCHAR(40) NULL,
    window_start_at        NVARCHAR(40) NULL,
    reg_source_id          INT NULL REFERENCES hp_reg_sources(id),
    reg_clause             NVARCHAR(200) NULL,
    status                 NVARCHAR(20) NOT NULL DEFAULT 'not_started'
                           CHECK (status IN ('not_started','in_progress','completed','exception')),
    response_value         NVARCHAR(2000) NULL,
    response_ok            INT NULL,
    evidence_id            INT NULL REFERENCES hp_evidence(id),
    comment                NVARCHAR(2000) NULL,
    exception_details      NVARCHAR(2000) NULL,
    started_at             NVARCHAR(40) NULL,
    completed_at           NVARCHAR(40) NULL,
    completed_by_user_id   INT NULL REFERENCES hp_users(id),
    completed_by_staff_id  INT NULL REFERENCES hp_staff(id),
    verification_status    NVARCHAR(10) NULL CHECK (verification_status IN ('pending','verified','rejected')),
    verified_by_user_id    INT NULL REFERENCES hp_users(id),
    verified_at            NVARCHAR(40) NULL,
    verification_note      NVARCHAR(2000) NULL,
    created_at             NVARCHAR(40) NOT NULL,
    created_by             INT NULL,
    -- Same "no duplicate instance" rule as the SQLite build.
    assigned_key AS ISNULL(assigned_staff_id, 0) PERSISTED
);
CREATE UNIQUE INDEX ux_hp_duty_instance
    ON hp_duties(schedule_id, template_item_id, duty_date, assigned_key)
    WHERE schedule_id IS NOT NULL AND template_item_id IS NOT NULL;
CREATE INDEX ix_hp_duty_date_dept ON hp_duties(duty_date, department_id, status);
CREATE INDEX ix_hp_duty_staff ON hp_duties(assigned_staff_id, duty_date);
CREATE INDEX ix_hp_duty_verif ON hp_duties(verification_status, department_id);

CREATE TABLE hp_expiry_categories (
    id                          INT IDENTITY(1,1) PRIMARY KEY,
    name                        NVARCHAR(80) NOT NULL UNIQUE,
    kind                        NVARCHAR(20) NOT NULL CHECK (kind IN ('food','beverage','prepared_food','chemical','first_aid','supply','other')),
    reminder_days               INT NOT NULL DEFAULT 3,
    shelf_life_after_open_days  INT NULL,
    shelf_life_after_prep_days  INT NULL,
    requires_evidence           INT NOT NULL DEFAULT 0,
    procedure_note              NVARCHAR(2000) NULL,
    active                      INT NOT NULL DEFAULT 1,
    created_at                  NVARCHAR(40) NOT NULL,
    created_by                  INT NULL,
    updated_at                  NVARCHAR(40) NULL,
    updated_by                  INT NULL
);

CREATE TABLE hp_expiry_items (
    id                    INT IDENTITY(1,1) PRIMARY KEY,
    name                  NVARCHAR(120) NOT NULL,
    category_id           INT NOT NULL REFERENCES hp_expiry_categories(id),
    department_id         INT NOT NULL REFERENCES hp_departments(id),
    location              NVARCHAR(120) NULL,
    batch_lot             NVARCHAR(60) NULL,
    quantity              FLOAT NULL,
    unit                  NVARCHAR(20) NULL,
    date_type             NVARCHAR(12) NOT NULL DEFAULT 'use_by' CHECK (date_type IN ('use_by','best_before','expiry')),
    expiry_date           NVARCHAR(10) NOT NULL,
    opened_on             NVARCHAR(10) NULL,
    prepared_on           NVARCHAR(10) NULL,
    responsible_staff_id  INT NULL REFERENCES hp_staff(id),
    state                 NVARCHAR(20) NOT NULL DEFAULT 'active'
                          CHECK (state IN ('active','action_required','removed','disposed')),
    last_checked_at       NVARCHAR(40) NULL,
    last_checked_by       INT NULL,
    notes                 NVARCHAR(2000) NULL,
    is_demo               INT NOT NULL DEFAULT 0,
    created_at            NVARCHAR(40) NOT NULL,
    created_by            INT NULL,
    updated_at            NVARCHAR(40) NULL,
    updated_by            INT NULL
);
CREATE INDEX ix_hp_exp_dept ON hp_expiry_items(department_id, state, expiry_date);

CREATE TABLE hp_expiry_actions (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    item_id       INT NOT NULL REFERENCES hp_expiry_items(id),
    action        NVARCHAR(20) NOT NULL CHECK (action IN ('checked_ok','removed','disposed','replaced','escalated','action_required')),
    note          NVARCHAR(2000) NULL,
    evidence_id   INT NULL REFERENCES hp_evidence(id),
    performed_by  INT NOT NULL REFERENCES hp_users(id),
    performed_at  NVARCHAR(40) NOT NULL
);
CREATE INDEX ix_hp_expact_item ON hp_expiry_actions(item_id);

CREATE TABLE hp_corrective_actions (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    source_type     NVARCHAR(20) NOT NULL CHECK (source_type IN ('duty','expiry','certification','observation','score','manual')),
    source_id       INT NULL,
    department_id   INT NULL REFERENCES hp_departments(id),
    staff_id        INT NULL REFERENCES hp_staff(id),
    title           NVARCHAR(200) NOT NULL,
    description     NVARCHAR(MAX) NULL,
    severity        NVARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high','critical')),
    owner_user_id   INT NULL REFERENCES hp_users(id),
    due_date        NVARCHAR(10) NULL,
    status          NVARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','cancelled')),
    resolution      NVARCHAR(MAX) NULL,
    resolved_by     INT NULL REFERENCES hp_users(id),
    resolved_at     NVARCHAR(40) NULL,
    created_at      NVARCHAR(40) NOT NULL,
    created_by      INT NULL,
    updated_at      NVARCHAR(40) NULL,
    updated_by      INT NULL
);
CREATE INDEX ix_hp_ca_status ON hp_corrective_actions(status, department_id);
CREATE INDEX ix_hp_ca_staff ON hp_corrective_actions(staff_id);

CREATE TABLE hp_alerts (
    id               INT IDENTITY(1,1) PRIMARY KEY,
    alert_key        NVARCHAR(200) NOT NULL UNIQUE,
    alert_type       NVARCHAR(40) NOT NULL,
    severity         NVARCHAR(10) NOT NULL,
    entity_type      NVARCHAR(40) NOT NULL,
    entity_id        INT NOT NULL,
    department_id    INT NULL,
    staff_id         INT NULL,
    message          NVARCHAR(1000) NOT NULL,
    created_at       NVARCHAR(40) NOT NULL,
    acknowledged_by  INT NULL,
    acknowledged_at  NVARCHAR(40) NULL
);
CREATE INDEX ix_hp_alert_open ON hp_alerts(acknowledged_at, department_id);

CREATE TABLE hp_score_criteria (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    name           NVARCHAR(80) NOT NULL,
    description    NVARCHAR(1000) NULL,
    source         NVARCHAR(30) NOT NULL CHECK (source IN ('manual','auto_duty_completion','auto_training')),
    category       NVARCHAR(20) NOT NULL DEFAULT 'observation'
                   CHECK (category IN ('duty','observation','training','exception','other')),
    weight         FLOAT NOT NULL DEFAULT 1 CHECK (weight >= 0),
    department_id  INT NULL REFERENCES hp_departments(id),
    active         INT NOT NULL DEFAULT 1,
    created_at     NVARCHAR(40) NOT NULL,
    created_by     INT NULL,
    updated_at     NVARCHAR(40) NULL,
    updated_by     INT NULL
);

CREATE TABLE hp_scores (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    staff_id       INT NOT NULL REFERENCES hp_staff(id),
    criterion_id   INT NOT NULL REFERENCES hp_score_criteria(id),
    score          FLOAT NOT NULL,
    scale_max      FLOAT NOT NULL,
    score_date     NVARCHAR(10) NOT NULL,
    reason         NVARCHAR(2000) NOT NULL,
    source_type    NVARCHAR(20) NULL CHECK (source_type IN ('duty','observation','training','exception','other')),
    source_id      INT NULL,
    awarded_by     INT NOT NULL REFERENCES hp_users(id),
    awarded_at     NVARCHAR(40) NOT NULL,
    voided         INT NOT NULL DEFAULT 0,
    voided_by      INT NULL,
    voided_at      NVARCHAR(40) NULL,
    void_reason    NVARCHAR(1000) NULL
);
CREATE INDEX ix_hp_scores_staff ON hp_scores(staff_id, score_date);

CREATE TABLE hp_coaching_notes (
    id                INT IDENTITY(1,1) PRIMARY KEY,
    staff_id          INT NOT NULL REFERENCES hp_staff(id),
    note              NVARCHAR(MAX) NOT NULL,
    visible_to_staff  INT NOT NULL DEFAULT 1,
    follow_up_date    NVARCHAR(10) NULL,
    resolved_at       NVARCHAR(40) NULL,
    resolved_by       INT NULL,
    resolution        NVARCHAR(2000) NULL,
    created_at        NVARCHAR(40) NOT NULL,
    created_by        INT NOT NULL
);
CREATE INDEX ix_hp_coach_staff ON hp_coaching_notes(staff_id);

CREATE TABLE hp_audit_log (
    id             BIGINT IDENTITY(1,1) PRIMARY KEY,
    at             NVARCHAR(40) NOT NULL,
    user_id        INT NULL,
    username       NVARCHAR(60) NULL,
    action         NVARCHAR(60) NOT NULL,
    entity_type    NVARCHAR(40) NOT NULL,
    entity_id      INT NULL,
    department_id  INT NULL,
    details        NVARCHAR(MAX) NULL
);
CREATE INDEX ix_hp_audit_at ON hp_audit_log(at);
CREATE INDEX ix_hp_audit_entity ON hp_audit_log(entity_type, entity_id);
