-- Optional demo objects for manual experiments.
-- The real checker does not require this file.
-- This script intentionally creates one collation with a wrong stored version.

DROP SCHEMA IF EXISTS pgcollcheck_demo CASCADE;

CREATE SCHEMA pgcollcheck_demo;

CREATE COLLATION pgcollcheck_demo.en_us_mismatch (
    provider = libc,
    locale = 'en_US.utf8',
    version = '0'
);

CREATE TABLE pgcollcheck_demo.sample_strings (
    id integer PRIMARY KEY,
    name text NOT NULL,
    nickname text NOT NULL,
    code text COLLATE "C" NOT NULL,
    email text NOT NULL
);

INSERT INTO pgcollcheck_demo.sample_strings (id, name, nickname, code, email)
VALUES
    (1, 'Ёлка', 'elka', 'A001', 'elka@example.test'),
    (2, 'Ель', 'yel', 'A002', 'yel@example.test'),
    (3, 'ångström', 'angstrom', 'A003', 'angstrom@example.test'),
    (4, 'apple', 'Apple', 'A004', 'apple@example.test'),
    (5, 'Äpfel', 'apfel', 'A005', 'apfel@example.test');

CREATE INDEX sample_strings_name_mismatch_idx
    ON pgcollcheck_demo.sample_strings (name COLLATE pgcollcheck_demo.en_us_mismatch);

CREATE INDEX sample_strings_nickname_default_idx
    ON pgcollcheck_demo.sample_strings (nickname);

CREATE INDEX sample_strings_code_c_idx
    ON pgcollcheck_demo.sample_strings (code COLLATE "C");
