-- Heygen Passport initial schema.
-- All tables are prefixed hp_ so they can never collide with other systems
-- if this database file is ever shared. Timestamps are stored as UTC ISO-8601
-- text; business dates (duty_date, expiry_date) are hotel-local YYYY-MM-DD.

CREATE TABLE hp_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_by  INTEGER,
    updated_at  TEXT NOT NULL
);

CREATE TABLE hp_departments (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE hp_outlets (
    id             INTEGER PRIMARY KEY,
    department_id  INTEGER REFERENCES hp_departments(id),
    name           TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    UNIQUE (department_id, name)
);

CREATE TABLE hp_evidence (
    id           INTEGER PRIMARY KEY,
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    data         BLOB NOT NULL,
    uploaded_by  INTEGER,
    uploaded_at  TEXT NOT NULL
);

CREATE TABLE hp_staff (
    id                   INTEGER PRIMARY KEY,
    employee_id          TEXT NOT NULL UNIQUE,
    full_name            TEXT NOT NULL,
    photo_evidence_id    INTEGER REFERENCES hp_evidence(id),
    job_title            TEXT NOT NULL,
    department_id        INTEGER NOT NULL REFERENCES hp_departments(id),
    employment_status    TEXT NOT NULL DEFAULT 'active'
                         CHECK (employment_status IN ('active','on_leave','suspended','terminated')),
    work_phone           TEXT,
    work_email           TEXT,
    start_date           TEXT,
    outlet_id            INTEGER REFERENCES hp_outlets(id),
    supervisor_staff_id  INTEGER REFERENCES hp_staff(id),
    shift_pattern        TEXT,
    notes                TEXT,
    is_demo              INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    created_by           INTEGER,
    updated_at           TEXT,
    updated_by           INTEGER
);
CREATE INDEX ix_hp_staff_dept ON hp_staff(department_id, employment_status);
CREATE INDEX ix_hp_staff_name ON hp_staff(full_name);

CREATE TABLE hp_users (
    id                    INTEGER PRIMARY KEY,
    username              TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash         TEXT NOT NULL,
    role                  TEXT NOT NULL CHECK (role IN ('staff','supervisor','manager','admin')),
    staff_id              INTEGER UNIQUE REFERENCES hp_staff(id),
    department_id         INTEGER REFERENCES hp_departments(id),
    can_score             INTEGER NOT NULL DEFAULT 0,
    active                INTEGER NOT NULL DEFAULT 1,
    must_change_password  INTEGER NOT NULL DEFAULT 1,
    failed_attempts       INTEGER NOT NULL DEFAULT 0,
    locked_until          TEXT,
    last_login_at         TEXT,
    is_demo               INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    created_by            INTEGER,
    updated_at            TEXT,
    updated_by            INTEGER
);

-- Configurable extra profile fields.
CREATE TABLE hp_profile_fields (
    id                INTEGER PRIMARY KEY,
    field_key         TEXT NOT NULL UNIQUE,
    label             TEXT NOT NULL,
    field_type        TEXT NOT NULL DEFAULT 'text' CHECK (field_type IN ('text','date','number','yes_no')),
    visible_to_staff  INTEGER NOT NULL DEFAULT 1,
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL
);

CREATE TABLE hp_staff_field_values (
    staff_id    INTEGER NOT NULL REFERENCES hp_staff(id),
    field_id    INTEGER NOT NULL REFERENCES hp_profile_fields(id),
    value       TEXT,
    updated_at  TEXT NOT NULL,
    updated_by  INTEGER,
    PRIMARY KEY (staff_id, field_id)
);

CREATE TABLE hp_certifications (
    id                    INTEGER PRIMARY KEY,
    staff_id              INTEGER NOT NULL REFERENCES hp_staff(id),
    name                  TEXT NOT NULL,
    cert_type             TEXT NOT NULL DEFAULT 'food_safety',
    issuer                TEXT,
    certificate_no        TEXT,
    issue_date            TEXT,
    expiry_date           TEXT,
    evidence_id           INTEGER REFERENCES hp_evidence(id),
    created_at            TEXT NOT NULL,
    created_by            INTEGER,
    updated_at            TEXT,
    updated_by            INTEGER
);
CREATE INDEX ix_hp_cert_expiry ON hp_certifications(expiry_date);
CREATE INDEX ix_hp_cert_staff ON hp_certifications(staff_id);

-- Traceable regulatory / procedure references for checklist items.
CREATE TABLE hp_reg_sources (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    authority     TEXT NOT NULL,
    document_ref  TEXT,
    version       TEXT,
    url           TEXT,
    review_date   TEXT,
    notes         TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    created_by    INTEGER,
    updated_at    TEXT,
    updated_by    INTEGER
);

CREATE TABLE hp_templates (
    id             INTEGER PRIMARY KEY,
    department_id  INTEGER NOT NULL REFERENCES hp_departments(id),
    name           TEXT NOT NULL,
    description    TEXT,
    is_starter     INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    created_by     INTEGER,
    updated_at     TEXT,
    updated_by     INTEGER
);

CREATE TABLE hp_template_items (
    id                     INTEGER PRIMARY KEY,
    template_id            INTEGER NOT NULL REFERENCES hp_templates(id),
    title                  TEXT NOT NULL,
    instructions           TEXT,
    response_type          TEXT NOT NULL CHECK (response_type IN ('yes_no','pass_fail','numeric','text','photo')),
    min_value              REAL,
    max_value              REAL,
    unit                   TEXT,
    priority               TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high')),
    risk_level             TEXT NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low','medium','high','critical')),
    requires_verification  INTEGER NOT NULL DEFAULT 0,
    due_time               TEXT,          -- HH:MM hotel local time
    window_minutes         INTEGER NOT NULL DEFAULT 60,
    sort_order             INTEGER NOT NULL DEFAULT 0,
    reg_source_id          INTEGER REFERENCES hp_reg_sources(id),
    reg_clause             TEXT,
    active                 INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL,
    created_by             INTEGER,
    updated_at             TEXT,
    updated_by             INTEGER
);
CREATE INDEX ix_hp_titem_tpl ON hp_template_items(template_id, active);

-- A schedule assigns a template to a department/outlet/role/shift over dates.
CREATE TABLE hp_schedules (
    id                 INTEGER PRIMARY KEY,
    template_id        INTEGER NOT NULL REFERENCES hp_templates(id),
    department_id      INTEGER NOT NULL REFERENCES hp_departments(id),
    outlet_id          INTEGER REFERENCES hp_outlets(id),
    job_title          TEXT,      -- optional role filter
    shift              TEXT NOT NULL DEFAULT 'any' CHECK (shift IN ('any','morning','afternoon','night')),
    assigned_staff_id  INTEGER REFERENCES hp_staff(id),
    start_date         TEXT NOT NULL,
    end_date           TEXT,
    days_of_week       TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',  -- Monday=0
    active             INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL,
    created_by         INTEGER,
    updated_at         TEXT,
    updated_by         INTEGER
);
CREATE INDEX ix_hp_sched_dept ON hp_schedules(department_id, active);

-- Concrete duty instances for a given date (snapshot of the template item).
CREATE TABLE hp_duties (
    id                     INTEGER PRIMARY KEY,
    schedule_id            INTEGER REFERENCES hp_schedules(id),
    template_item_id       INTEGER REFERENCES hp_template_items(id),
    duty_date              TEXT NOT NULL,
    department_id          INTEGER NOT NULL REFERENCES hp_departments(id),
    outlet_id              INTEGER REFERENCES hp_outlets(id),
    job_title              TEXT,
    shift                  TEXT NOT NULL DEFAULT 'any',
    assigned_staff_id      INTEGER REFERENCES hp_staff(id),
    title                  TEXT NOT NULL,
    instructions           TEXT,
    response_type          TEXT NOT NULL,
    min_value              REAL,
    max_value              REAL,
    unit                   TEXT,
    priority               TEXT NOT NULL,
    risk_level             TEXT NOT NULL,
    requires_verification  INTEGER NOT NULL DEFAULT 0,
    due_at                 TEXT,           -- UTC
    window_start_at        TEXT,           -- UTC
    reg_source_id          INTEGER REFERENCES hp_reg_sources(id),
    reg_clause             TEXT,
    status                 TEXT NOT NULL DEFAULT 'not_started'
                           CHECK (status IN ('not_started','in_progress','completed','exception')),
    response_value         TEXT,
    response_ok            INTEGER,       -- 1 pass, 0 fail, NULL not evaluated
    evidence_id            INTEGER REFERENCES hp_evidence(id),
    comment                TEXT,
    exception_details      TEXT,
    started_at             TEXT,
    completed_at           TEXT,
    completed_by_user_id   INTEGER REFERENCES hp_users(id),
    completed_by_staff_id  INTEGER REFERENCES hp_staff(id),
    verification_status    TEXT CHECK (verification_status IN ('pending','verified','rejected')),
    verified_by_user_id    INTEGER REFERENCES hp_users(id),
    verified_at            TEXT,
    verification_note      TEXT,
    created_at             TEXT NOT NULL,
    created_by             INTEGER
);
CREATE UNIQUE INDEX ux_hp_duty_instance
    ON hp_duties(schedule_id, template_item_id, duty_date, IFNULL(assigned_staff_id, 0));
CREATE INDEX ix_hp_duty_date_dept ON hp_duties(duty_date, department_id, status);
CREATE INDEX ix_hp_duty_staff ON hp_duties(assigned_staff_id, duty_date);
CREATE INDEX ix_hp_duty_verif ON hp_duties(verification_status, department_id);

CREATE TABLE hp_expiry_categories (
    id                        INTEGER PRIMARY KEY,
    name                      TEXT NOT NULL UNIQUE,
    kind                      TEXT NOT NULL CHECK (kind IN ('food','beverage','prepared_food','chemical','first_aid','supply','other')),
    reminder_days             INTEGER NOT NULL DEFAULT 3,
    shelf_life_after_open_days INTEGER,   -- NULL = no opened-item rule
    shelf_life_after_prep_days INTEGER,   -- NULL = no prepared-food rule
    requires_evidence         INTEGER NOT NULL DEFAULT 0,
    procedure_note            TEXT,
    active                    INTEGER NOT NULL DEFAULT 1,
    created_at                TEXT NOT NULL,
    created_by                INTEGER,
    updated_at                TEXT,
    updated_by                INTEGER
);

CREATE TABLE hp_expiry_items (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL,
    category_id           INTEGER NOT NULL REFERENCES hp_expiry_categories(id),
    department_id         INTEGER NOT NULL REFERENCES hp_departments(id),
    location              TEXT,
    batch_lot             TEXT,
    quantity              REAL,
    unit                  TEXT,
    date_type             TEXT NOT NULL DEFAULT 'use_by' CHECK (date_type IN ('use_by','best_before','expiry')),
    expiry_date           TEXT NOT NULL,
    opened_on             TEXT,
    prepared_on           TEXT,
    responsible_staff_id  INTEGER REFERENCES hp_staff(id),
    state                 TEXT NOT NULL DEFAULT 'active'
                          CHECK (state IN ('active','action_required','removed','disposed')),
    last_checked_at       TEXT,
    last_checked_by       INTEGER,
    notes                 TEXT,
    is_demo               INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL,
    created_by            INTEGER,
    updated_at            TEXT,
    updated_by            INTEGER
);
CREATE INDEX ix_hp_exp_dept ON hp_expiry_items(department_id, state, expiry_date);

CREATE TABLE hp_expiry_actions (
    id            INTEGER PRIMARY KEY,
    item_id       INTEGER NOT NULL REFERENCES hp_expiry_items(id),
    action        TEXT NOT NULL CHECK (action IN ('checked_ok','removed','disposed','replaced','escalated','action_required')),
    note          TEXT,
    evidence_id   INTEGER REFERENCES hp_evidence(id),
    performed_by  INTEGER NOT NULL REFERENCES hp_users(id),
    performed_at  TEXT NOT NULL
);
CREATE INDEX ix_hp_expact_item ON hp_expiry_actions(item_id);

CREATE TABLE hp_corrective_actions (
    id              INTEGER PRIMARY KEY,
    source_type     TEXT NOT NULL CHECK (source_type IN ('duty','expiry','certification','observation','score','manual')),
    source_id       INTEGER,
    department_id   INTEGER REFERENCES hp_departments(id),
    staff_id        INTEGER REFERENCES hp_staff(id),
    title           TEXT NOT NULL,
    description     TEXT,
    severity        TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high','critical')),
    owner_user_id   INTEGER REFERENCES hp_users(id),
    due_date        TEXT,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','cancelled')),
    resolution      TEXT,
    resolved_by     INTEGER REFERENCES hp_users(id),
    resolved_at     TEXT,
    created_at      TEXT NOT NULL,
    created_by      INTEGER,
    updated_at      TEXT,
    updated_by      INTEGER
);
CREATE INDEX ix_hp_ca_status ON hp_corrective_actions(status, department_id);
CREATE INDEX ix_hp_ca_staff ON hp_corrective_actions(staff_id);

CREATE TABLE hp_alerts (
    id               INTEGER PRIMARY KEY,
    alert_key        TEXT NOT NULL UNIQUE,
    alert_type       TEXT NOT NULL,
    severity         TEXT NOT NULL,
    entity_type      TEXT NOT NULL,
    entity_id        INTEGER NOT NULL,
    department_id    INTEGER,
    staff_id         INTEGER,
    message          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    acknowledged_by  INTEGER,
    acknowledged_at  TEXT
);
CREATE INDEX ix_hp_alert_open ON hp_alerts(acknowledged_at, department_id);

CREATE TABLE hp_score_criteria (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT,
    source         TEXT NOT NULL CHECK (source IN ('manual','auto_duty_completion','auto_training')),
    category       TEXT NOT NULL DEFAULT 'observation'
                   CHECK (category IN ('duty','observation','training','exception','other')),
    weight         REAL NOT NULL DEFAULT 1 CHECK (weight >= 0),
    department_id  INTEGER REFERENCES hp_departments(id),
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    created_by     INTEGER,
    updated_at     TEXT,
    updated_by     INTEGER
);

CREATE TABLE hp_scores (
    id             INTEGER PRIMARY KEY,
    staff_id       INTEGER NOT NULL REFERENCES hp_staff(id),
    criterion_id   INTEGER NOT NULL REFERENCES hp_score_criteria(id),
    score          REAL NOT NULL,
    scale_max      REAL NOT NULL,
    score_date     TEXT NOT NULL,
    reason         TEXT NOT NULL,
    source_type    TEXT CHECK (source_type IN ('duty','observation','training','exception','other')),
    source_id      INTEGER,
    awarded_by     INTEGER NOT NULL REFERENCES hp_users(id),
    awarded_at     TEXT NOT NULL,
    voided         INTEGER NOT NULL DEFAULT 0,
    voided_by      INTEGER,
    voided_at      TEXT,
    void_reason    TEXT
);
CREATE INDEX ix_hp_scores_staff ON hp_scores(staff_id, score_date);

CREATE TABLE hp_coaching_notes (
    id                INTEGER PRIMARY KEY,
    staff_id          INTEGER NOT NULL REFERENCES hp_staff(id),
    note              TEXT NOT NULL,
    visible_to_staff  INTEGER NOT NULL DEFAULT 1,
    follow_up_date    TEXT,
    resolved_at       TEXT,
    resolved_by       INTEGER,
    resolution        TEXT,
    created_at        TEXT NOT NULL,
    created_by        INTEGER NOT NULL
);
CREATE INDEX ix_hp_coach_staff ON hp_coaching_notes(staff_id);

CREATE TABLE hp_audit_log (
    id             INTEGER PRIMARY KEY,
    at             TEXT NOT NULL,
    user_id        INTEGER,
    username       TEXT,
    action         TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER,
    department_id  INTEGER,
    details        TEXT
);
CREATE INDEX ix_hp_audit_at ON hp_audit_log(at);
CREATE INDEX ix_hp_audit_entity ON hp_audit_log(entity_type, entity_id);
