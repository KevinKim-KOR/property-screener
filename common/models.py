def get_schema_queries():
    """
    SQLite DB 초기화에 사용될 DDL 쿼리 리스트를 반환합니다.
    SCORING_V2 명세서(§6.1, §6.2)에 따른 신규 테이블 및 확장 인덱스 전량을 포함합니다.
    """
    return [
        """
        CREATE TABLE IF NOT EXISTS properties (
            property_id TEXT PRIMARY KEY,
            complex_code TEXT,
            complex_name TEXT,
            region_name TEXT,
            building_dong TEXT,
            floor TEXT,
            high_price INTEGER,
            asking_price INTEGER,
            area_pyeong REAL,
            drop_rate REAL,
            change_1m REAL,
            change_3m REAL,
            change_6m REAL,
            registered_date TEXT,
            updated_at TEXT,
            area_type TEXT,
            exclusive_area REAL,
            deal_gap_pct REAL,
            floor_grade TEXT,
            score_v1 REAL,
            last_seen_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sent_alerts (
            property_id TEXT PRIMARY KEY,
            asking_price INTEGER,
            sent_at TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(property_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS complexes (
            complex_code      TEXT PRIMARY KEY,
            complex_name      TEXT NOT NULL,
            sgg_cd            TEXT NOT NULL,
            umd_cd            TEXT,
            region_name       TEXT,
            build_year        INTEGER,
            total_households  INTEGER,
            total_dongs       INTEGER,
            floor_area_ratio  REAL,
            building_coverage REAL,
            brand             TEXT,
            lat               REAL,
            lng               REAL,
            subway_dist_m     REAL,
            subway_name       TEXT,
            subway_walk_min   REAL,
            elem_school_dist_m REAL,
            cbd_transit_min   REAL,
            bonbun            INTEGER,
            bubun             INTEGER,
            road_name         TEXT,
            area_min_m2       REAL,
            area_max_m2       REAL,
            updated_at        TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS complex_key_map (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            complex_code    TEXT,
            sgg_cd          TEXT NOT NULL,
            umd_nm          TEXT NOT NULL,
            bonbun          INTEGER,
            bubun           INTEGER,
            road_name       TEXT,
            apt_name_raw    TEXT NOT NULL,
            apt_name_norm   TEXT NOT NULL,
            build_year      INTEGER,
            confidence      REAL NOT NULL DEFAULT 0.0,
            match_method    TEXT NOT NULL,
            status          TEXT NOT NULL,
            reviewed_at     TEXT,
            UNIQUE(sgg_cd, umd_nm, bonbun, bubun, apt_name_norm)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS trades_sale (
            trade_id        TEXT PRIMARY KEY,
            complex_code    TEXT,
            sgg_cd          TEXT NOT NULL,
            umd_nm          TEXT,
            bonbun          INTEGER,
            bubun           INTEGER,
            road_name       TEXT,
            apt_name_raw    TEXT NOT NULL,
            exclusive_area  REAL NOT NULL,
            area_type       TEXT,
            deal_date       TEXT NOT NULL,
            deal_amount     INTEGER NOT NULL,
            building_dong   TEXT,
            floor           INTEGER,
            buyer_type      TEXT,
            seller_type     TEXT,
            build_year      INTEGER,
            is_cancelled    INTEGER NOT NULL DEFAULT 0,
            cancel_date     TEXT,
            deal_type       TEXT,
            agent_region    TEXT,
            registry_date   TEXT,
            source          TEXT NOT NULL,
            source_snapshot_date TEXT,
            first_seen_date TEXT,
            last_seen_date  TEXT,
            ingested_at     TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_trades_sale_key
            ON trades_sale(complex_code, area_type, deal_date)
        """,
        """
        CREATE TABLE IF NOT EXISTS trades_rent (
            rent_id         TEXT PRIMARY KEY,
            complex_code    TEXT,
            sgg_cd          TEXT NOT NULL,
            apt_name_raw    TEXT NOT NULL,
            exclusive_area  REAL NOT NULL,
            area_type       TEXT,
            deal_date       TEXT NOT NULL,
            deposit         INTEGER NOT NULL,
            monthly_rent    INTEGER NOT NULL DEFAULT 0,
            floor           INTEGER,
            contract_type   TEXT,
            ingested_at     TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_trades_rent_key
            ON trades_rent(complex_code, area_type, deal_date)
        """,
        """
        CREATE TABLE IF NOT EXISTS listing_snapshots (
            snapshot_date   TEXT NOT NULL,
            complex_code    TEXT NOT NULL,
            area_type       TEXT NOT NULL,
            listing_count   INTEGER NOT NULL,
            min_ask_price   INTEGER,
            median_ask_price INTEGER,
            PRIMARY KEY (snapshot_date, complex_code, area_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS complex_area_stats (
            base_date            TEXT NOT NULL,
            complex_code         TEXT NOT NULL,
            area_type            TEXT NOT NULL,
            median_price_3m      REAL,
            peak_price_raw       REAL,
            peak_price_adj       REAL,
            peak_date            TEXT,
            drop_rate            REAL,
            excess_drop_rate     REAL,
            jeonse_ratio         REAL,
            price_per_pyeong     REAL,
            rent_yield           REAL,
            trade_count_3m       INTEGER,
            trade_count_12m      INTEGER,
            volume_ratio         REAL,
            listing_delta_30d    REAL,
            momentum_3m          REAL,
            supply_pressure      REAL,
            households_log       REAL,
            age_years            REAL,
            far_score            REAL,
            special_deal_ratio   REAL,
            sample_count_12m     INTEGER,
            sample_count_24m     INTEGER,
            m3                   REAL,
            m6                   REAL,
            m12                  REAL,
            computed_at          TEXT NOT NULL,
            PRIMARY KEY (base_date, complex_code, area_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_scores (
            run_id           TEXT NOT NULL,
            base_date        TEXT NOT NULL,
            complex_code     TEXT NOT NULL,
            area_type        TEXT NOT NULL,
            peer_group_key   TEXT NOT NULL,
            peer_group_n     INTEGER NOT NULL,
            block_value      REAL,
            block_flow       REAL,
            block_location   REAL,
            block_quality    REAL,
            raw_score        REAL,
            base_score       REAL,
            risk_multiplier  REAL NOT NULL DEFAULT 1.0,
            market_score     REAL,
            gate_status      TEXT NOT NULL,
            gate_reason      TEXT,
            coverage_ratio   REAL,
            evidence_json    TEXT NOT NULL,
            PRIMARY KEY (run_id, complex_code, area_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS score_runs (
            run_id          TEXT PRIMARY KEY,
            run_at          TEXT NOT NULL,
            base_date       TEXT NOT NULL,
            config_hash     TEXT NOT NULL,
            scorer_version  TEXT NOT NULL,
            universe_total  INTEGER NOT NULL,
            universe_passed INTEGER NOT NULL,
            excluded_count  INTEGER NOT NULL,
            duration_sec    REAL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS region_stats (
            base_date       TEXT NOT NULL,
            sgg_cd          TEXT NOT NULL,
            area_type       TEXT NOT NULL,
            median_drop_rate REAL,
            median_ppp      REAL,
            median_jeonse_ratio REAL,
            sample_n        INTEGER NOT NULL,
            supply_ratio    REAL,
            unsold_delta_3m REAL,
            PRIMARY KEY (base_date, sgg_cd, area_type)
        )
        """
    ]
