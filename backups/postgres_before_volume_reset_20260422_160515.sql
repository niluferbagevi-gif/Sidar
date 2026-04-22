--
-- PostgreSQL database cluster dump
--

\restrict dToPBHmvt0CkUTE1WcI6O84xadgdffkjcA4DpkxiaL4vLFW6IumtQ5aOe4r1GJb

SET default_transaction_read_only = off;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

--
-- Roles
--

CREATE ROLE sidar;
ALTER ROLE sidar WITH SUPERUSER INHERIT CREATEROLE CREATEDB LOGIN REPLICATION BYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:DBWWbnxeHI5ZNo38JCCHow==$YYTWPp/B1i2XdGmhPOQH1M3SYawWZijAPLlAOLZ4VtY=:Re/r/LuCSzcZ4dKmG+pn/MjM61oEGtA/uNjTAMt/kYw=';

--
-- User Configurations
--








\unrestrict dToPBHmvt0CkUTE1WcI6O84xadgdffkjcA4DpkxiaL4vLFW6IumtQ5aOe4r1GJb

--
-- Databases
--

--
-- Database "template1" dump
--

\connect template1

--
-- PostgreSQL database dump
--

\restrict QutCjpuevYmjnb1IIIcgUIzwYZNGgqQuLuB24ycpZVR2GKpklFL6u8Gpn9cN0Gp

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- PostgreSQL database dump complete
--

\unrestrict QutCjpuevYmjnb1IIIcgUIzwYZNGgqQuLuB24ycpZVR2GKpklFL6u8Gpn9cN0Gp

--
-- Database "postgres" dump
--

\connect postgres

--
-- PostgreSQL database dump
--

\restrict hZCxgG9mrrpfkdwOiMOgoSbb7xnM1U6NNI4vOcBsmJLA23D6cKexu4feF2ifPBA

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- PostgreSQL database dump complete
--

\unrestrict hZCxgG9mrrpfkdwOiMOgoSbb7xnM1U6NNI4vOcBsmJLA23D6cKexu4feF2ifPBA

--
-- Database "sidar" dump
--

--
-- PostgreSQL database dump
--

\restrict KPK7m7Wlnem7gtzAzqKVp0qjDn8HXOE0Hd7gCzZA4hA2U9zWsgfmEy8J1qifMLD

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: sidar; Type: DATABASE; Schema: -; Owner: sidar
--

CREATE DATABASE sidar WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'en_US.utf8';


ALTER DATABASE sidar OWNER TO sidar;

\unrestrict KPK7m7Wlnem7gtzAzqKVp0qjDn8HXOE0Hd7gCzZA4hA2U9zWsgfmEy8J1qifMLD
\connect sidar
\restrict KPK7m7Wlnem7gtzAzqKVp0qjDn8HXOE0Hd7gCzZA4hA2U9zWsgfmEy8J1qifMLD

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_policies; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.access_policies (
    id bigint NOT NULL,
    user_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    resource_type text NOT NULL,
    resource_id text DEFAULT '*'::text NOT NULL,
    action text NOT NULL,
    effect text DEFAULT 'allow'::text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.access_policies OWNER TO sidar;

--
-- Name: access_policies_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.access_policies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.access_policies_id_seq OWNER TO sidar;

--
-- Name: access_policies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.access_policies_id_seq OWNED BY public.access_policies.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO sidar;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    user_id text DEFAULT ''::text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    action text NOT NULL,
    resource text NOT NULL,
    ip_address text NOT NULL,
    allowed boolean DEFAULT false NOT NULL,
    "timestamp" timestamp with time zone NOT NULL
);


ALTER TABLE public.audit_logs OWNER TO sidar;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_logs_id_seq OWNER TO sidar;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: auth_tokens; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.auth_tokens (
    token text NOT NULL,
    user_id character varying(36) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.auth_tokens OWNER TO sidar;

--
-- Name: content_assets; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.content_assets (
    id bigint NOT NULL,
    campaign_id bigint NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    asset_type text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    channel text DEFAULT 'generic'::text NOT NULL,
    metadata_json text DEFAULT '{}'::text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.content_assets OWNER TO sidar;

--
-- Name: content_assets_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.content_assets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.content_assets_id_seq OWNER TO sidar;

--
-- Name: content_assets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.content_assets_id_seq OWNED BY public.content_assets.id;


--
-- Name: coverage_findings; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.coverage_findings (
    id bigint NOT NULL,
    task_id bigint NOT NULL,
    finding_type text NOT NULL,
    target_path text DEFAULT ''::text NOT NULL,
    summary text NOT NULL,
    severity text DEFAULT 'info'::text NOT NULL,
    details_json text DEFAULT '{}'::text NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.coverage_findings OWNER TO sidar;

--
-- Name: coverage_findings_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.coverage_findings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.coverage_findings_id_seq OWNER TO sidar;

--
-- Name: coverage_findings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.coverage_findings_id_seq OWNED BY public.coverage_findings.id;


--
-- Name: coverage_tasks; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.coverage_tasks (
    id bigint NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    requester_role text NOT NULL,
    command text NOT NULL,
    pytest_output text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    target_path text DEFAULT ''::text NOT NULL,
    suggested_test_path text DEFAULT ''::text NOT NULL,
    review_payload_json text DEFAULT '{}'::text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.coverage_tasks OWNER TO sidar;

--
-- Name: coverage_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.coverage_tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.coverage_tasks_id_seq OWNER TO sidar;

--
-- Name: coverage_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.coverage_tasks_id_seq OWNED BY public.coverage_tasks.id;


--
-- Name: marketing_campaigns; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.marketing_campaigns (
    id bigint NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    name text NOT NULL,
    channel text NOT NULL,
    objective text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    owner_user_id text DEFAULT 'system'::text NOT NULL,
    budget numeric(14,2) DEFAULT '0'::numeric NOT NULL,
    metadata_json text DEFAULT '{}'::text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.marketing_campaigns OWNER TO sidar;

--
-- Name: marketing_campaigns_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.marketing_campaigns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.marketing_campaigns_id_seq OWNER TO sidar;

--
-- Name: marketing_campaigns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.marketing_campaigns_id_seq OWNED BY public.marketing_campaigns.id;


--
-- Name: messages; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.messages (
    id bigint NOT NULL,
    session_id character varying(36) NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    tokens_used integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.messages OWNER TO sidar;

--
-- Name: messages_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.messages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.messages_id_seq OWNER TO sidar;

--
-- Name: messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.messages_id_seq OWNED BY public.messages.id;


--
-- Name: operation_checklists; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.operation_checklists (
    id bigint NOT NULL,
    campaign_id bigint,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    title text NOT NULL,
    items_json text DEFAULT '[]'::text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    owner_user_id text DEFAULT 'system'::text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.operation_checklists OWNER TO sidar;

--
-- Name: operation_checklists_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.operation_checklists_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.operation_checklists_id_seq OWNER TO sidar;

--
-- Name: operation_checklists_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.operation_checklists_id_seq OWNED BY public.operation_checklists.id;


--
-- Name: prompt_registry; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.prompt_registry (
    id integer NOT NULL,
    role_name text NOT NULL,
    prompt_text text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.prompt_registry OWNER TO sidar;

--
-- Name: prompt_registry_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.prompt_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.prompt_registry_id_seq OWNER TO sidar;

--
-- Name: prompt_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.prompt_registry_id_seq OWNED BY public.prompt_registry.id;


--
-- Name: provider_usage_daily; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.provider_usage_daily (
    id bigint NOT NULL,
    user_id character varying(36) NOT NULL,
    provider text NOT NULL,
    usage_date date NOT NULL,
    requests_used integer DEFAULT 0 NOT NULL,
    tokens_used integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.provider_usage_daily OWNER TO sidar;

--
-- Name: provider_usage_daily_id_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.provider_usage_daily_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.provider_usage_daily_id_seq OWNER TO sidar;

--
-- Name: provider_usage_daily_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.provider_usage_daily_id_seq OWNED BY public.provider_usage_daily.id;


--
-- Name: schema_versions; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.schema_versions (
    version integer NOT NULL,
    applied_at timestamp with time zone NOT NULL,
    description text NOT NULL
);


ALTER TABLE public.schema_versions OWNER TO sidar;

--
-- Name: schema_versions_version_seq; Type: SEQUENCE; Schema: public; Owner: sidar
--

CREATE SEQUENCE public.schema_versions_version_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.schema_versions_version_seq OWNER TO sidar;

--
-- Name: schema_versions_version_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: sidar
--

ALTER SEQUENCE public.schema_versions_version_seq OWNED BY public.schema_versions.version;


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.sessions (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    title text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.sessions OWNER TO sidar;

--
-- Name: user_quotas; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.user_quotas (
    user_id character varying(36) NOT NULL,
    daily_token_limit integer DEFAULT 0 NOT NULL,
    daily_request_limit integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.user_quotas OWNER TO sidar;

--
-- Name: users; Type: TABLE; Schema: public; Owner: sidar
--

CREATE TABLE public.users (
    id character varying(36) NOT NULL,
    username text NOT NULL,
    password_hash text,
    role text DEFAULT 'user'::text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL
);


ALTER TABLE public.users OWNER TO sidar;

--
-- Name: access_policies id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.access_policies ALTER COLUMN id SET DEFAULT nextval('public.access_policies_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: content_assets id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.content_assets ALTER COLUMN id SET DEFAULT nextval('public.content_assets_id_seq'::regclass);


--
-- Name: coverage_findings id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.coverage_findings ALTER COLUMN id SET DEFAULT nextval('public.coverage_findings_id_seq'::regclass);


--
-- Name: coverage_tasks id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.coverage_tasks ALTER COLUMN id SET DEFAULT nextval('public.coverage_tasks_id_seq'::regclass);


--
-- Name: marketing_campaigns id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.marketing_campaigns ALTER COLUMN id SET DEFAULT nextval('public.marketing_campaigns_id_seq'::regclass);


--
-- Name: messages id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.messages ALTER COLUMN id SET DEFAULT nextval('public.messages_id_seq'::regclass);


--
-- Name: operation_checklists id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.operation_checklists ALTER COLUMN id SET DEFAULT nextval('public.operation_checklists_id_seq'::regclass);


--
-- Name: prompt_registry id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.prompt_registry ALTER COLUMN id SET DEFAULT nextval('public.prompt_registry_id_seq'::regclass);


--
-- Name: provider_usage_daily id; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.provider_usage_daily ALTER COLUMN id SET DEFAULT nextval('public.provider_usage_daily_id_seq'::regclass);


--
-- Name: schema_versions version; Type: DEFAULT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.schema_versions ALTER COLUMN version SET DEFAULT nextval('public.schema_versions_version_seq'::regclass);


--
-- Data for Name: access_policies; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.access_policies (id, user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.alembic_version (version_num) FROM stdin;
0005_pgvector_hnsw_index
\.


--
-- Data for Name: audit_logs; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.audit_logs (id, user_id, tenant_id, action, resource, ip_address, allowed, "timestamp") FROM stdin;
\.


--
-- Data for Name: auth_tokens; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.auth_tokens (token, user_id, expires_at, created_at) FROM stdin;
\.


--
-- Data for Name: content_assets; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.content_assets (id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: coverage_findings; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.coverage_findings (id, task_id, finding_type, target_path, summary, severity, details_json, created_at) FROM stdin;
\.


--
-- Data for Name: coverage_tasks; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.coverage_tasks (id, tenant_id, requester_role, command, pytest_output, status, target_path, suggested_test_path, review_payload_json, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: marketing_campaigns; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.marketing_campaigns (id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: messages; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.messages (id, session_id, role, content, tokens_used, created_at) FROM stdin;
1	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 06:33:26.320259+00
2	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 06:33:26.322953+00
3	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 06:33:29.188591+00
4	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 06:33:29.191441+00
5	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 06:33:30.179668+00
6	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 06:33:30.187559+00
7	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 06:33:33.066818+00
8	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 06:33:33.075526+00
9	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:06:07.712685+00
10	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 07:06:07.71639+00
11	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:06:10.24785+00
12	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 07:06:10.253602+00
13	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 07:06:13.281998+00
14	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 07:06:13.290232+00
15	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 07:06:15.823695+00
16	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 07:06:15.826847+00
17	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:17:41.785663+00
18	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 07:17:41.788277+00
19	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:17:44.434345+00
20	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 07:17:44.440261+00
21	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 07:17:47.113325+00
22	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 07:17:47.121399+00
23	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 07:17:49.685322+00
24	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 07:17:49.693496+00
25	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:32:32.453873+00
26	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 07:32:32.457748+00
27	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:32:37.538386+00
28	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 07:32:37.543962+00
29	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 07:32:43.726219+00
30	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 07:32:43.73398+00
31	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 07:32:47.281299+00
32	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 07:32:47.289872+00
33	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:40:59.779506+00
34	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 07:40:59.781926+00
35	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:41:02.403288+00
36	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 07:41:02.40541+00
37	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 07:41:04.878528+00
38	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 07:41:04.88135+00
39	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 07:41:07.443294+00
40	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 07:41:07.451479+00
41	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:52:34.594742+00
42	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 07:52:34.597307+00
43	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:52:37.198961+00
44	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 07:52:37.201398+00
45	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 07:52:40.14895+00
46	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 07:52:40.156803+00
47	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 07:52:42.851216+00
48	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 07:52:42.859137+00
49	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:58:57.70265+00
50	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 07:58:57.705345+00
51	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 07:59:02.386096+00
52	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 07:59:02.388548+00
53	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 07:59:05.930394+00
54	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 07:59:05.938264+00
55	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 07:59:10.696337+00
56	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 07:59:10.703683+00
57	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:06:27.312642+00
58	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 08:06:27.315382+00
59	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:06:30.245674+00
60	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 08:06:30.251311+00
61	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 08:06:38.943758+00
62	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 08:06:38.951528+00
63	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 08:06:41.595285+00
64	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 08:06:41.603203+00
65	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:13:05.803815+00
66	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 08:13:05.806264+00
67	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:13:12.23329+00
68	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 08:13:12.236003+00
69	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 08:13:18.062439+00
70	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 08:13:18.070776+00
71	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 08:13:24.064568+00
72	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 08:13:24.067354+00
73	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:20:14.044149+00
74	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 08:20:14.047273+00
75	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:20:17.192034+00
76	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 08:20:17.194328+00
77	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 08:20:20.179881+00
78	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 08:20:20.188132+00
79	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 08:20:23.23608+00
80	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 08:20:23.243739+00
81	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:28:07.485805+00
82	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 08:28:07.488601+00
83	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:28:10.584488+00
84	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 08:28:10.587832+00
85	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 08:28:14.922315+00
86	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 08:28:14.931259+00
87	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 08:28:19.029083+00
88	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 08:28:19.031645+00
89	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:33:38.687011+00
90	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 08:33:38.691247+00
91	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 08:33:42.19219+00
92	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 08:33:42.197595+00
93	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 08:33:45.22115+00
94	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 08:33:45.228772+00
95	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 08:33:48.079521+00
96	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 08:33:48.087493+00
97	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:12:07.304195+00
98	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 09:12:07.307959+00
99	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:12:11.905876+00
100	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 09:12:11.910624+00
101	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 09:12:16.820351+00
102	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 09:12:16.828967+00
103	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 09:12:21.781943+00
104	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 09:12:21.790059+00
105	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:21:46.606996+00
106	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 09:21:46.609566+00
107	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:21:51.679496+00
108	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 09:21:51.681696+00
109	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 09:21:59.98199+00
110	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 09:21:59.990063+00
111	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 09:22:11.741514+00
112	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 09:22:11.749379+00
113	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:35:31.897515+00
114	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 09:35:31.901238+00
115	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:35:34.906708+00
116	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 09:35:34.911834+00
117	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 09:35:37.911856+00
118	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 09:35:37.91488+00
119	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 09:35:41.866568+00
120	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 09:35:41.874266+00
121	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:48:26.174654+00
122	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 09:48:26.178345+00
123	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:48:32.354135+00
124	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 09:48:32.356315+00
125	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 09:48:41.737523+00
126	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 09:48:41.745698+00
127	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 09:48:51.307967+00
128	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 09:48:51.3156+00
129	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:56:25.015947+00
130	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 09:56:25.018757+00
131	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 09:56:28.001943+00
132	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 09:56:28.004373+00
133	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 09:56:31.441867+00
134	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 09:56:31.449579+00
135	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 09:56:34.821549+00
136	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 09:56:34.828961+00
137	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:01:54.676294+00
138	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 10:01:54.679188+00
139	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:01:57.743592+00
140	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 10:01:57.748689+00
141	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 10:02:01.223845+00
142	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 10:02:01.232063+00
143	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 10:02:05.292532+00
144	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 10:02:05.300212+00
145	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:08:30.099841+00
146	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 10:08:30.103096+00
147	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:08:33.664954+00
148	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 10:08:33.667381+00
149	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 10:08:37.747856+00
150	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 10:08:37.755405+00
151	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 10:08:43.646384+00
152	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 10:08:43.653879+00
153	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:16:57.757591+00
154	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 10:16:57.760408+00
155	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:17:04.807517+00
156	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 10:17:04.812574+00
157	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 10:17:11.99705+00
158	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 10:17:12.004664+00
159	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 10:17:24.357869+00
160	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 10:17:24.361001+00
161	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:57:07.368535+00
162	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 10:57:07.371899+00
163	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 10:57:10.084725+00
164	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 10:57:10.087397+00
165	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 10:57:13.112909+00
166	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 10:57:13.120566+00
167	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 10:57:18.367176+00
168	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 10:57:18.375263+00
169	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 11:22:28.424833+00
170	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 11:22:28.428637+00
171	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 11:22:46.905218+00
172	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 11:22:46.907985+00
173	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 11:23:06.570696+00
174	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 11:23:06.579053+00
175	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 11:23:17.67723+00
176	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 11:23:17.68527+00
177	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 11:43:12.286527+00
178	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 11:43:12.290215+00
179	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 11:43:27.094605+00
180	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 11:43:27.099552+00
181	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 11:43:44.456591+00
182	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 11:43:44.46491+00
183	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 11:44:05.559953+00
184	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 11:44:05.567935+00
185	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 12:01:09.254696+00
186	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 12:01:09.258401+00
187	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 12:01:12.027618+00
188	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 12:01:12.030519+00
189	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 12:01:15.325623+00
190	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 12:01:15.334524+00
191	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 12:01:18.529557+00
192	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 12:01:18.537893+00
193	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 12:30:03.928643+00
194	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 12:30:03.932913+00
195	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 12:30:19.96329+00
196	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 12:30:19.965732+00
197	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 12:30:25.747357+00
198	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 12:30:25.755212+00
199	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 12:30:30.335632+00
200	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 12:30:30.344222+00
201	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 12:43:43.93749+00
202	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	docs:ok:docs için araştırma yap	0	2026-04-22 12:43:43.940377+00
203	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	docs için araştırma yap	0	2026-04-22 12:43:46.660183+00
204	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Arama sırasında hata oluştu: docs için araştırma yap	0	2026-04-22 12:43:46.663054+00
205	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Pytest entegrasyonunu araştır	0	2026-04-22 12:43:49.327986+00
206	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Araştırma tamamlandı.	0	2026-04-22 12:43:49.336442+00
207	80b4fcbb-9244-4972-83b6-3c4b7b6489af	user	Depodaki dokümanları ara	0	2026-04-22 12:43:52.498072+00
208	80b4fcbb-9244-4972-83b6-3c4b7b6489af	assistant	Doküman araması şu anda kullanılamıyor.	0	2026-04-22 12:43:52.506426+00
\.


--
-- Data for Name: operation_checklists; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.operation_checklists (id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: prompt_registry; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.prompt_registry (id, role_name, prompt_text, version, is_active, created_at, updated_at) FROM stdin;
1	system	Sen SİDAR'sın — Yazılım Mimarı ve Baş Mühendis.\nVarsayılan olarak yerel Ollama ile çalışabilirsin; ancak sağlayıcı Gemini ise internet bağlantısı gerekir.\n\n## KİŞİLİK\n- Analitik ve disiplinli — geek ruhu\n- Minimal ve öz konuşur; gereksiz söz söylemez\n- Veriye dayalı karar verir; duygusal değil\n- Algoritma ve metriklere odaklanır\n- Güvenliğe şüpheci yaklaşır; her şeyi doğrular\n\n## MİSYON\nYerel proje dosyalarına erişmek, GitHub ile senkronize çalışmak, kod yönetimi,\nsistem optimizasyonu, gerçek zamanlı araştırma ve teknik denetim konularında birinci\nsınıf destek sağlamak.\n\n## GÜNCEL RUNTIME KİMLİĞİ\n- Web arayüzü varsayılan portu: `7860` (localhost üzerinden erişim).\n- Ollama varsayılan kod modeli: `qwen2.5-coder:7b`.\n- Gemini varsayılan model: `gemini-2.5-flash`.\n- Bu değerler değişebilir; nihai doğrulama için `get_config` çıktısını esas al.\n\n## BİLGİ SINIRI — KRİTİK\n- Model eğitim verisi 2025 yılı ortasına (Ağustos 2025) kadar günceldir.\n- Bu tarihten sonraki kütüphane sürümleri, API değişiklikleri veya yeni framework'ler\n  hakkında TAHMIN ETME — bunun yerine 'web_search' veya 'pypi' aracını kullan.\n\n## HALLUCINATION YASAĞI — MUTLAK KURAL\n- Proje adı, versiyon, AI sağlayıcı, model adı, dizin yolu, erişim seviyesi\n  gibi sistem değerlerini ASLA TAHMİN ETME.\n- Bu değerler sana her turda "[Proje Ayarları — GERÇEK RUNTIME DEĞERLERİ]"\n  bloğunda verilir. Yalnızca o bloktaki değerleri kullan.\n- Eğer bu değerlere ihtiyaç duyarsan 'get_config' aracını çağır — UYDURMA.\n\n## DOSYA ERİŞİM STRATEJİSİ — TEMEL\n- Proje dizinini öğrenmek için önce 'get_config' aracını kullan (BASE_DIR değeri).\n- Belirli dosyaları bulmak için `glob_search` kullan (örn: `**/*.py`).\n- Dosya içinde kod/metin aramak için `grep_files` kullan (regex destekler).\n- Proje dosyalarını taramak için: önce `list_dir` ile klasör içeriğine bak,\n  ardından `read_file` ile her dosyayı oku (satır numaralı gösterim).\n- Birden fazla dosyayı düzeltirken: `read_file` → analiz → `patch_file` (küçük değişiklik)\n  veya `write_file` (tam yeniden yazma) sırasını uygula.\n- Git, npm, pip gibi sistem komutları için `run_shell` kullan (ACCESS_LEVEL=full gerekir).\n- GitHub'daki dosyaları okumak için `github_read`, GitHub'a yazmak için `github_write`.\n\n## GÖREV TAKİP STRATEJİSİ — TEMEL\n- Karmaşık çok adımlı görevlerde MUTLAKA `todo_write` ile görev listesi oluştur.\n- Göreve başlamadan önce listeye ekle, tamamlandığında `todo_update` ile 'completed' işaretle.\n- `todo_read` ile mevcut görev listesini kontrol et.\n- Basit tek adımlı görevler için todo listesi gerekmez.\n- Alt görev (subtask) yürütürken sistem limitlerine (örn. SUBTASK_MAX_STEPS) uyarak otonom ilerleyebilirsin.\n\n## SIDAR.md — PROJE ÖZEL TALİMATLAR\n- Proje kökünde SIDAR.md dosyası varsa, proje özel talimatlar otomatik yüklenir.\n- SIDAR.md içeriği her turda sistem bağlamına eklenir (Claude Code'daki CLAUDE.md gibi).\n- SIDAR.md'yi oluşturmak için: `write_file` ile `SIDAR.md` dosyasına yaz.\n\n## İLKELER\n1. PEP 8 standartlarında kod yaz.\n2. Kod yazmadan önce MÜMKÜNSE `execute_code` ile test et (REPL).\n3. Dosyaları düzenlerken `patch_file` kullan, tamamını yeniden yazma.\n4. Hataları sınıflandır: sözdizimi / mantık / çalışma zamanı / yapılandırma.\n5. Performans metriklerini takip et.\n6. Dosya içeriklerinde UTF-8 kullan; Türkçe karakterleri güvenle koru.\n7. Sandbox fail-closed mantığını unutma: Docker erişilemezse execute_code güvenli şekilde durdurulabilir.\n\n## ARAÇ KULLANIM STRATEJİLERİ\n- **Kabuk Komutu (run_shell):** Git, npm, pip, make, test runner gibi sistem komutları → `run_shell`. ACCESS_LEVEL=full gerekir. Argüman: komut dizgesi (örn: "git status", "npm test", "pip list").\n- **Dosya Arama (glob_search):** "*.py dosyalarını bul", "src/ altındaki TS dosyaları" → `glob_search`. Argüman: "desen[|||dizin]" (örn: "**/*.py|||." veya "src/**/*.ts").\n- **İçerik Arama (grep_files):** "import AsyncIO nerede", "TODO yorumlarını bul" → `grep_files`. Argüman: "regex[|||yol[|||dosya_filtresi[|||bağlam_satırı]]]". Örn: "def run_shell|||.|||*.py|||2".\n- **Görev Listesi (todo_write):** Karmaşık çok adımlı görevlerde → `todo_write`. Argüman: "görev1:::pending|||görev2:::in_progress".\n- **Görev Görüntüle (todo_read):** Görevleri kontrol et → `todo_read`. Argüman: "" (boş).\n- **Görev Güncelle (todo_update):** Görev bitti/başladı → `todo_update`. Argüman: "görev_id|||yeni_durum" (örn: "1|||completed").\n- **Kod Çalıştırma (execute_code):** "kodu çalıştır", "test et", "sonucu göster" → `execute_code`. (Docker varsa izole konteyner, yoksa subprocess ile çalışır.)\n- **Sistem Sağlığı (health):** "sistem sağlık", "CPU/RAM/GPU durumu", "donanım raporu" → `health` kullan.\n- **GitHub Commits (github_commits):** "son commit", "commit geçmişi" → `github_commits` kullan. Not: Sayfalama/güvenlik nedeniyle en fazla son 30 commit döner. Mevcut araçların tam listesi için dispatch tablosunu esas al; source-of-truth `agent/sidar_agent.py` dosyasıdır.\n- **GitHub Dosya Listesi (github_list_files):** "GitHub'daki dosyaları listele", "depodaki dosyalar" → `github_list_files` kullan.\n- **GitHub Dosya Okuma (github_read):** "GitHub'dan oku", "uzak dosya" → `github_read` kullan.\n- **GitHub Dosya Yazma (github_write):** "GitHub'a yaz", "GitHub'da güncelle", "depoya kaydet" → `github_write`. Argüman: "path|||içerik|||commit_mesajı[|||branch]".\n- **GitHub Branch Oluşturma (github_create_branch):** "yeni dal oluştur", "branch aç" → `github_create_branch`. Argüman: "branch_adı[|||kaynak_branch]".\n- **GitHub Pull Request (github_create_pr):** "PR oluştur", "pull request aç" → `github_create_pr`. Argüman: "başlık|||açıklama|||head_branch[|||base_branch]".\n- **Akıllı PR Oluşturma (github_smart_pr):** "değişikliklerimi PR olarak aç", "otomatik PR oluştur", "PR yap" → `github_smart_pr`. Git diff/log analiz eder, LLM ile başlık+açıklama üretir. Argüman: "[head_branch[|||base_branch[|||ek_notlar]]]" (tümü opsiyonel).\n- **PR Listesi (github_list_prs):** "PR listesi", "açık pull requestler" → `github_list_prs`. Argüman: "state[|||limit]" (state: open/closed/all). Not: Limit belirtilmezse güvenli varsayılan sayfa boyutu uygulanır.\n- **PR Detayı (github_get_pr):** "PR #5 detayı", "12 numaralı PR" → `github_get_pr`. Argüman: PR numarası.\n- **PR Yorum (github_comment_pr):** "PR'a yorum ekle", "#5'e yorum yaz" → `github_comment_pr`. Argüman: "pr_no|||yorum".\n- **PR Kapat (github_close_pr):** "PR'ı kapat", "#3'ü kapat" → `github_close_pr`. Argüman: PR numarası.\n- **PR Dosyaları (github_pr_files):** "PR'daki değişiklikler", "#7 PR dosyaları" → `github_pr_files`. Argüman: PR numarası.\n- **GitHub Kod Arama (github_search_code):** "depoda ara", "kod içinde bul" → `github_search_code`. Argüman: arama_sorgusu.\n- **Paket Sürümü (pypi):** "PyPI sürümü", "paketin sürümü" → `pypi`. Sonucu aldıktan sonra HEMEN `final_answer` ver.\n- **Dosya Tarama:** → önce `glob_search` ile dosyaları bul, sonra `read_file` ile oku (satır numaraları otomatik gösterilir).\n- **Config Değerleri:** "model nedir?", "gerçek ayarlar", "proje dizini" → `get_config`.\n- **Web İçerik Çekme (fetch_url):** URL içeriği getirir. Not: İçerik 12.000 karakterden uzunsa otomatik kırpılır.\n- **Belge Ekleme (docs_add):** "URL'yi belge deposuna ekle" → `docs_add`. Argüman: "başlık|url".\n- **Yerel Dosya RAG (docs_add_file):** "Bu dosyayı RAG'a ekle", "büyük dosyayı hafızaya al", "dosyayı belge deposuna ekle" → `docs_add_file`. Argüman: "dosya_yolu" veya "başlık|dosya_yolu". Büyük (>20K karakter) dosyaları `read_file` ile okuduktan sonra bu araçla RAG'a ekleyin — tekrar okuma gerekmez.\n- **Dosya Düzenleme (patch_file):** Küçük değişiklikler için `patch_file` kullan. Argüman: "path|||eski_kod|||yeni_kod".\n\n## DÖNGÜ YASAĞI — KRİTİK\n- Aynı aracı art arda ASLA iki kez çağırma. Bir araç sonuç döndürdüyse `final_answer` ver.\n- Aşağıdaki araçlar **tek adımda** tüm sonucu döndürür — hata almadıkça bir daha çağırma:\n  `pypi`, `web_search`, `health`, `github_commits`, `get_config`, `print_config_summary`,\n  `github_info`, `audit`, `docs_list`, `gh_latest`, `todo_read`, `glob_search`, `grep_files`,\n  `github_list_prs`, `github_get_pr`, `github_pr_files`, `github_smart_pr`.\n- Hata aldıysan: farklı bir araç dene veya `final_answer` ile hatayı kullanıcıya bildir.\n- Sistem "döngü tespit edildi" uyarısı verirse: HEMEN `final_answer` kullan.\n\n## HATA KURTARMA\n- Dosya bulunamadı → `list_dir` ile dizini doğrula, yolu düzelt.\n- Patch hatası → `read_file` ile dosyayı oku, tam eşleşmeyi sağla.\n- İzin hatası → erişim seviyesini `get_config` ile kontrol et.\n- Web araması sonuçsuz → Sorguyu genelleştir veya İngilizce terimler kullan.\n- GitHub yazma hatası → token ve depo adını kontrol et; `github_info` ile doğrula.\n\n## ARAÇ KULLANIMI (JSON FORMATI)\nYanıtlarını MUTLAKA geçerli bir JSON nesnesi olarak ver.\nAsla düz metin veya markdown bloğu kullanma.\n\nŞema:\n{\n  "thought": "Düşünme süreci (kısa akıl yürütme)",\n  "tool": "araç_adı",\n  "argument": "araç_argümanı"\n}\n\n## ÖRNEK JSON YANITLARI\n\n1. Kullanıcı: "Bana 100'e kadar asal sayıları bulan bir kod yaz."\n{\n  "thought": "Önce kodu yazıp execute_code ile test etmeliyim.",\n  "tool": "execute_code",\n  "argument": "def is_prime(n):\\n    if n <= 1: return False\\n    for i in range(2, int(n**0.5)+1):\\n        if n % i == 0: return False\\n    return True\\nprimes = [n for n in range(2, 101) if is_prime(n)]\\nprint(primes)"\n}\n\n2. Kullanıcı: "main.py dosyasını oku ve ne işe yaradığını açıkla."\n{\n  "thought": "Dosyayı okuyarak içeriğini analiz edeceğim.",\n  "tool": "read_file",\n  "argument": "main.py"\n}\n\n3. Kullanıcı: "FastAPI'nin son sürümünü kontrol et."\n{\n  "thought": "PyPI ile güncel sürümü sorguluyorum.",\n  "tool": "pypi",\n  "argument": "fastapi"\n}\n\n4. Kullanıcı: "Bu dosyayı GitHub'a commit et."\n{\n  "thought": "github_write aracı ile dosyayı depoya yüklüyorum.",\n  "tool": "github_write",\n  "argument": "managers/code_manager.py|||<dosya_içeriği>|||feat: kod yöneticisi güncellendi"\n}\n\n5. Kullanıcı: "Araç çıktısı aldıktan sonra veya soruyu yanıtladıktan sonra:"\n   → ASLA ham veri objesi döndürme. Yanıtını MUTLAKA final_answer argümanında ver.\n   YANLIŞ: {"project": "Sid", "version": "v1.0.0"}\n   DOĞRU : {"thought": "...", "tool": "final_answer", "argument": "**Proje:** Sid\\n**Sürüm:** v1.0.0"}\n	1	t	2026-04-22 06:31:53.050243+00	2026-04-22 06:31:53.050243+00
\.


--
-- Data for Name: provider_usage_daily; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.provider_usage_daily (id, user_id, provider, usage_date, requests_used, tokens_used) FROM stdin;
\.


--
-- Data for Name: schema_versions; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.schema_versions (version, applied_at, description) FROM stdin;
1	2026-04-22 06:33:23.653756+00	baseline migration v1
\.


--
-- Data for Name: sessions; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.sessions (id, user_id, title, created_at, updated_at) FROM stdin;
80b4fcbb-9244-4972-83b6-3c4b7b6489af	integration-user	Yeni Sohbet	2026-04-22 06:33:24.955007+00	2026-04-22 06:33:24.955007+00
\.


--
-- Data for Name: user_quotas; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.user_quotas (user_id, daily_token_limit, daily_request_limit) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: sidar
--

COPY public.users (id, username, password_hash, role, created_at, tenant_id) FROM stdin;
integration-user	Integration User	\N	user	2026-04-22 06:33:24.952166+00	default
\.


--
-- Name: access_policies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.access_policies_id_seq', 1, false);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.audit_logs_id_seq', 1, false);


--
-- Name: content_assets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.content_assets_id_seq', 1, false);


--
-- Name: coverage_findings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.coverage_findings_id_seq', 1, false);


--
-- Name: coverage_tasks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.coverage_tasks_id_seq', 1, false);


--
-- Name: marketing_campaigns_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.marketing_campaigns_id_seq', 1, false);


--
-- Name: messages_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.messages_id_seq', 208, true);


--
-- Name: operation_checklists_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.operation_checklists_id_seq', 1, false);


--
-- Name: prompt_registry_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.prompt_registry_id_seq', 1, true);


--
-- Name: provider_usage_daily_id_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.provider_usage_daily_id_seq', 1, false);


--
-- Name: schema_versions_version_seq; Type: SEQUENCE SET; Schema: public; Owner: sidar
--

SELECT pg_catalog.setval('public.schema_versions_version_seq', 1, false);


--
-- Name: access_policies access_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.access_policies
    ADD CONSTRAINT access_policies_pkey PRIMARY KEY (id);


--
-- Name: access_policies access_policies_user_id_tenant_id_resource_type_resource_id_key; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.access_policies
    ADD CONSTRAINT access_policies_user_id_tenant_id_resource_type_resource_id_key UNIQUE (user_id, tenant_id, resource_type, resource_id, action);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: auth_tokens auth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (token);


--
-- Name: content_assets content_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.content_assets
    ADD CONSTRAINT content_assets_pkey PRIMARY KEY (id);


--
-- Name: coverage_findings coverage_findings_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.coverage_findings
    ADD CONSTRAINT coverage_findings_pkey PRIMARY KEY (id);


--
-- Name: coverage_tasks coverage_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.coverage_tasks
    ADD CONSTRAINT coverage_tasks_pkey PRIMARY KEY (id);


--
-- Name: marketing_campaigns marketing_campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.marketing_campaigns
    ADD CONSTRAINT marketing_campaigns_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: operation_checklists operation_checklists_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.operation_checklists
    ADD CONSTRAINT operation_checklists_pkey PRIMARY KEY (id);


--
-- Name: prompt_registry prompt_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.prompt_registry
    ADD CONSTRAINT prompt_registry_pkey PRIMARY KEY (id);


--
-- Name: provider_usage_daily provider_usage_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.provider_usage_daily
    ADD CONSTRAINT provider_usage_daily_pkey PRIMARY KEY (id);


--
-- Name: schema_versions schema_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.schema_versions
    ADD CONSTRAINT schema_versions_pkey PRIMARY KEY (version);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: prompt_registry uq_prompt_registry_role_version; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.prompt_registry
    ADD CONSTRAINT uq_prompt_registry_role_version UNIQUE (role_name, version);


--
-- Name: provider_usage_daily uq_provider_usage_daily; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.provider_usage_daily
    ADD CONSTRAINT uq_provider_usage_daily UNIQUE (user_id, provider, usage_date);


--
-- Name: user_quotas user_quotas_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.user_quotas
    ADD CONSTRAINT user_quotas_pkey PRIMARY KEY (user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: idx_access_policies_user_tenant; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_access_policies_user_tenant ON public.access_policies USING btree (user_id, tenant_id, resource_type, action);


--
-- Name: idx_audit_logs_timestamp; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_audit_logs_timestamp ON public.audit_logs USING btree ("timestamp");


--
-- Name: idx_audit_logs_user_timestamp; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_audit_logs_user_timestamp ON public.audit_logs USING btree (user_id, "timestamp");


--
-- Name: idx_auth_tokens_user_id; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_auth_tokens_user_id ON public.auth_tokens USING btree (user_id);


--
-- Name: idx_content_assets_campaign_tenant; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_content_assets_campaign_tenant ON public.content_assets USING btree (campaign_id, tenant_id, asset_type);


--
-- Name: idx_coverage_findings_task; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_coverage_findings_task ON public.coverage_findings USING btree (task_id, finding_type, severity);


--
-- Name: idx_coverage_tasks_tenant_status; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_coverage_tasks_tenant_status ON public.coverage_tasks USING btree (tenant_id, status, updated_at);


--
-- Name: idx_marketing_campaigns_tenant_status; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_marketing_campaigns_tenant_status ON public.marketing_campaigns USING btree (tenant_id, status, updated_at);


--
-- Name: idx_messages_session_id; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_messages_session_id ON public.messages USING btree (session_id);


--
-- Name: idx_operation_checklists_campaign_tenant; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_operation_checklists_campaign_tenant ON public.operation_checklists USING btree (campaign_id, tenant_id, status);


--
-- Name: idx_prompt_registry_role_active; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_prompt_registry_role_active ON public.prompt_registry USING btree (role_name, is_active);


--
-- Name: idx_provider_usage_daily_user_id; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_provider_usage_daily_user_id ON public.provider_usage_daily USING btree (user_id);


--
-- Name: idx_sessions_user_id; Type: INDEX; Schema: public; Owner: sidar
--

CREATE INDEX idx_sessions_user_id ON public.sessions USING btree (user_id);


--
-- Name: access_policies access_policies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.access_policies
    ADD CONSTRAINT access_policies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: auth_tokens auth_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: content_assets content_assets_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.content_assets
    ADD CONSTRAINT content_assets_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.marketing_campaigns(id) ON DELETE CASCADE;


--
-- Name: coverage_findings coverage_findings_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.coverage_findings
    ADD CONSTRAINT coverage_findings_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.coverage_tasks(id) ON DELETE CASCADE;


--
-- Name: messages messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: operation_checklists operation_checklists_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.operation_checklists
    ADD CONSTRAINT operation_checklists_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.marketing_campaigns(id) ON DELETE SET NULL;


--
-- Name: provider_usage_daily provider_usage_daily_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.provider_usage_daily
    ADD CONSTRAINT provider_usage_daily_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_quotas user_quotas_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: sidar
--

ALTER TABLE ONLY public.user_quotas
    ADD CONSTRAINT user_quotas_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict KPK7m7Wlnem7gtzAzqKVp0qjDn8HXOE0Hd7gCzZA4hA2U9zWsgfmEy8J1qifMLD

--
-- PostgreSQL database cluster dump complete
--

