BEGIN;

DROP TABLE IF EXISTS hunt_logs;
DROP TABLE IF EXISTS wanted_criminals;

CREATE TABLE wanted_criminals (
    id                 SERIAL PRIMARY KEY,
    name               VARCHAR(120),
    nickname           VARCHAR(120) NOT NULL,
    reward             BIGINT       NOT NULL,
    last_latitude      DOUBLE PRECISION,
    last_longitude     DOUBLE PRECISION,
    last_location_note TEXT,
    difficulty         INTEGER      NOT NULL,
    armed              BOOLEAN      NOT NULL DEFAULT FALSE,
    has_crew           BOOLEAN      NOT NULL DEFAULT FALSE,
    escape_master      BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_criminal_difficulty  CHECK (difficulty BETWEEN 1 AND 10),
    CONSTRAINT ck_criminal_reward      CHECK (reward >= 0),
    CONSTRAINT ck_criminal_coords_pair CHECK ((last_latitude IS NULL) = (last_longitude IS NULL)),
    CONSTRAINT ck_criminal_lat         CHECK (last_latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_criminal_lon         CHECK (last_longitude BETWEEN -180 AND 180)
);
CREATE INDEX ix_wanted_criminals_reward ON wanted_criminals (reward);

CREATE TABLE hunt_logs (
    id          SERIAL PRIMARY KEY,
    criminal_id INTEGER     NOT NULL REFERENCES wanted_criminals (id) ON DELETE CASCADE,
    success     BOOLEAN     NOT NULL,
    notes       TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_hunt_logs_criminal_id ON hunt_logs (criminal_id);

INSERT INTO wanted_criminals
    (name, nickname, reward, last_latitude, last_longitude, last_location_note, difficulty, armed, has_crew, escape_master)
VALUES
    ('Viktor Halloran', 'Red Comet',     12000000,  12.4500,  -45.2100, NULL,                                            9, TRUE,  TRUE,  TRUE),
    (NULL,              'The Ghost',      8500000,  NULL,      NULL,    'Last seen in the Titan ice markets',            8, FALSE, FALSE, TRUE),
    ('Marla Quince',    'Hex',             450000, -33.8600,  151.2100, 'Hiding near the Ganymede shipyards',            5, TRUE,  FALSE, FALSE),
    ('Duke Bramwell',   'Iron Duke',      3000000,  48.8566,    2.3522, NULL,                                            7, TRUE,  TRUE,  FALSE),
    ('Pip Okonkwo',     'Glitch',           90000,  NULL,      NULL,    'Runs scams from a casino ship in the asteroid belt', 2, FALSE, FALSE, FALSE),
    (NULL,              'Black Lotus',    6000000,  -1.2921,   36.8219, 'Moves between Mars colonies every few days',     8, TRUE,  TRUE,  TRUE);

INSERT INTO hunt_logs (criminal_id, success, notes, created_at) VALUES
    (1, FALSE, 'Ambushed at the Callisto gate, his crew covered the retreat.',  now() - INTERVAL '30 days'),
    (1, FALSE, 'Chased him through a debris field, lost him in the sensor shadow.', now() - INTERVAL '21 days'),
    (2, FALSE, 'Found only an empty apartment and a cold cup of coffee.',       now() - INTERVAL '19 days'),
    (2, FALSE, 'Tip from an informant was fake.',                               now() - INTERVAL '12 days'),
    (3, FALSE, 'Target escaped through an asteroid field.',                     now() - INTERVAL '15 days'),
    (3, TRUE,  'Cornered her in a cargo bay. Delivered to the police station.', now() - INTERVAL '10 days'),
    (4, FALSE, 'Too many bodyguards, aborted the mission.',                     now() - INTERVAL '9 days'),
    (4, FALSE, 'Shootout in the hangar, ship took heavy damage.',               now() - INTERVAL '6 days'),
    (5, TRUE,  'Caught him at the roulette table. Easy money.',                 now() - INTERVAL '5 days'),
    (6, FALSE, 'She switched ships mid-flight. Lost the trail.',                now() - INTERVAL '4 days'),
    (6, FALSE, 'Trap failed, her crew spotted the tracker.',                    now() - INTERVAL '2 days'),
    (1, FALSE, 'Got close on Io, but he jumped to hyperspace.',                 now() - INTERVAL '1 day');

COMMIT;