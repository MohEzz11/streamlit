-- Reverts 0001_initial (SQL Server). Only drops Heygen Passport (hp_) tables
-- inside the Heygen database.
-- The migrate command refuses to run this unless --confirm is passed,
-- and takes a COPY_ONLY .bak backup of the Heygen database first.
DROP TABLE IF EXISTS hp_audit_log;
DROP TABLE IF EXISTS hp_coaching_notes;
DROP TABLE IF EXISTS hp_scores;
DROP TABLE IF EXISTS hp_score_criteria;
DROP TABLE IF EXISTS hp_alerts;
DROP TABLE IF EXISTS hp_corrective_actions;
DROP TABLE IF EXISTS hp_expiry_actions;
DROP TABLE IF EXISTS hp_expiry_items;
DROP TABLE IF EXISTS hp_expiry_categories;
DROP TABLE IF EXISTS hp_duties;
DROP TABLE IF EXISTS hp_schedules;
DROP TABLE IF EXISTS hp_template_items;
DROP TABLE IF EXISTS hp_templates;
DROP TABLE IF EXISTS hp_reg_sources;
DROP TABLE IF EXISTS hp_certifications;
DROP TABLE IF EXISTS hp_staff_field_values;
DROP TABLE IF EXISTS hp_profile_fields;
DROP TABLE IF EXISTS hp_users;
DROP TABLE IF EXISTS hp_staff;
DROP TABLE IF EXISTS hp_evidence;
DROP TABLE IF EXISTS hp_outlets;
DROP TABLE IF EXISTS hp_departments;
DROP TABLE IF EXISTS hp_settings;
