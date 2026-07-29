-- 001_scoring_v2.sql
-- SCORING_V2_DESIGN.md (§6.2, §6.3) 마이그레이션 스크립트

-- properties 테이블 신규 컬럼 확장 (주의: SQLite ALTER TABLE ADD COLUMN은 컬럼 이미 존재 시 오류 발생하므로 프로그램에서 안전 처리)
ALTER TABLE properties ADD COLUMN area_type       TEXT;
ALTER TABLE properties ADD COLUMN exclusive_area  REAL;
ALTER TABLE properties ADD COLUMN deal_gap_pct    REAL;
ALTER TABLE properties ADD COLUMN floor_grade     TEXT;
ALTER TABLE properties ADD COLUMN score_v1        REAL;
ALTER TABLE properties ADD COLUMN last_seen_at    TEXT;
