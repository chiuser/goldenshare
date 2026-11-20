CREATE TABLE public.confirmed_business_facts (
    fact_id uuid NOT NULL,
    revision integer NOT NULL,
    action text NOT NULL,
    subject_type text NOT NULL,
    subject_key text NOT NULL,
    fact_type text NOT NULL,
    time_precision text NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_until timestamptz,
    evidence jsonb NOT NULL,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    recorded_by text NOT NULL DEFAULT session_user,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (fact_id, revision),
    CHECK (
        (revision = 1 AND action = 'confirm')
        OR (revision > 1 AND action IN ('correct', 'revoke'))
    ),
    CHECK (btrim(subject_type) <> '' AND btrim(subject_key) <> ''
           AND btrim(fact_type) <> ''),
    CHECK (time_precision IN ('day', 'timestamp')),
    CHECK (effective_until IS NULL OR effective_until > effective_from),
    CHECK (
        CASE WHEN jsonb_typeof(evidence) = 'array'
             THEN action = 'revoke' OR jsonb_array_length(evidence) > 0
             ELSE false END
    )
);

CREATE INDEX confirmed_business_facts_lookup_idx
    ON public.confirmed_business_facts
       (subject_type, fact_type, subject_key, fact_id, revision DESC);
