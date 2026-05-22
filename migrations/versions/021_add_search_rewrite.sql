CREATE TABLE IF NOT EXISTS search_synonyms (
    id SERIAL PRIMARY KEY,
    shop_domain TEXT NOT NULL,
    phrase_norm TEXT NOT NULL,
    phrase_raw TEXT,
    target_code TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (shop_domain, phrase_norm)
);

CREATE INDEX IF NOT EXISTS idx_search_synonyms_shop ON search_synonyms (shop_domain);
CREATE INDEX IF NOT EXISTS idx_search_synonyms_phrase ON search_synonyms (phrase_norm);
CREATE INDEX IF NOT EXISTS idx_search_synonyms_target ON search_synonyms (target_code);

CREATE TABLE IF NOT EXISTS inspo_targets (
    id SERIAL PRIMARY KEY,
    shop_domain TEXT NOT NULL,
    target_code TEXT NOT NULL,
    product_handle TEXT,
    product_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (shop_domain, target_code)
);

CREATE INDEX IF NOT EXISTS idx_inspo_targets_shop ON inspo_targets (shop_domain);
CREATE INDEX IF NOT EXISTS idx_inspo_targets_target ON inspo_targets (target_code);
