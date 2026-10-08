/**
 * Flow tag constants for consistent E2E test tagging.
 *
 * GENERATED FILE — do not edit by hand and do not resolve merge
 * conflicts manually: regenerate with
 *   python3 scripts/generate_flow_registry.py --repo-root .
 * Source of truth: the flow registry (flow-definitions shards or
 * flow-definitions.json). Authored extras live in flow-tags.extra.js.
 *
 * Usage:
 *   import { ADMIN_LOGIN } from '../helpers/flow-tags.js';
 *   test('...', { tag: [...ADMIN_LOGIN, '@role:admin'] }, async ({ page }) => { ... });
 */

// Registry version: 2.4.0

// ── auth ──
export const A3_ACCOUNT_SECURITY = ['@flow:a3-account-security', '@module:auth', '@priority:P2'];
export const AUTH_ADMIN_LOGIN_HANDOFF = ['@flow:auth-admin-login-handoff', '@module:auth', '@priority:P3'];
export const AUTH_FORGOT_PASSWORD_FORM = ['@flow:auth-forgot-password-form', '@module:auth', '@priority:P2'];
export const AUTH_LOGIN_INVALID = ['@flow:auth-login-invalid', '@module:auth', '@priority:P1'];
export const AUTH_PROTECTED_REDIRECT = ['@flow:auth-protected-redirect', '@module:auth', '@priority:P1'];
export const AUTH_SIGN_IN_FORM = ['@flow:auth-sign-in-form', '@module:auth', '@priority:P2'];
export const AUTH_SIGN_IN_SUCCESS = ['@flow:auth-sign-in-success', '@module:auth', '@priority:P1'];
export const AUTH_SIGN_OUT = ['@flow:auth-sign-out', '@module:auth', '@priority:P2'];
export const AUTH_SIGN_UP_FORM = ['@flow:auth-sign-up-form', '@module:auth', '@priority:P1'];

// ── billing ──
export const F1_BILLING = ['@flow:f1-billing', '@module:billing', '@priority:P2'];
export const F2_USAGE_PANEL = ['@flow:f2-usage-panel', '@module:billing', '@priority:P2'];
export const PUBLIC_PRICING = ['@flow:public-pricing', '@module:billing', '@priority:P1'];
export const TRIAL_VISIBILITY = ['@flow:trial-visibility', '@module:billing', '@priority:P2'];

// ── compare ──
export const E1_COMPARE = ['@flow:e1-compare', '@module:compare', '@priority:P1'];
export const E2_SAVED_COMPARISONS = ['@flow:e2-saved-comparisons', '@module:compare', '@priority:P2'];
export const E3_CONFIGURABLE_CHECKS = ['@flow:e3-configurable-checks', '@module:compare', '@priority:P2'];

// ── documents ──
export const C1_UPLOAD_FIRST = ['@flow:c1-upload-first', '@module:documents', '@priority:P1'];
export const C2_UPLOAD_VERSION = ['@flow:c2-upload-version', '@module:documents', '@priority:P1'];
export const C3_HISTORY = ['@flow:c3-history', '@module:documents', '@priority:P2'];
export const C4_DELETE_DRAFT = ['@flow:c4-delete-draft', '@module:documents', '@priority:P2'];

// ── home ──
export const HELP_MANUAL_BROWSE = ['@flow:help-manual-browse', '@module:home', '@priority:P3'];
export const HOME_LOADS = ['@flow:home-loads', '@module:home', '@priority:P1'];
export const LAYOUT_PUBLIC_NAVIGATION = ['@flow:layout-public-navigation', '@module:home', '@priority:P1'];

// ── master ──
export const MASTER_E2E_JOURNEY = ['@flow:master-e2e-journey', '@module:master', '@priority:P1'];

// ── onboarding ──
export const A1_ONBOARDING_WOW = ['@flow:a1-onboarding-wow', '@module:onboarding', '@priority:P1'];

// ── org ──
export const A2_INVITE_TEAM = ['@flow:a2-invite-team', '@module:org', '@priority:P1'];
export const F3_ORG_AUDIT = ['@flow:f3-org-audit', '@module:org', '@priority:P2'];
export const LAYOUT_AUTHENTICATED_NAVIGATION = ['@flow:layout-authenticated-navigation', '@module:org', '@priority:P1'];

// ── projects ──
export const B1_CREATE_PROJECT = ['@flow:b1-create-project', '@module:projects', '@priority:P1'];
export const B2_PROJECTS_BOARD = ['@flow:b2-projects-board', '@module:projects', '@priority:P2'];
export const B3_PROJECT_SETTINGS = ['@flow:b3-project-settings', '@module:projects', '@priority:P2'];
export const B4_ARCHIVE_DELETE = ['@flow:b4-archive-delete', '@module:projects', '@priority:P2'];

// ── public ──
export const PUBLIC_COMPARE = ['@flow:public-compare', '@module:public', '@priority:P1'];
export const PUBLIC_COMPARE_LIFECYCLE = ['@flow:public-compare-lifecycle', '@module:public', '@priority:P1'];

// ── review ──
export const D1_REQUEST_REVIEW = ['@flow:d1-request-review', '@module:review', '@priority:P1'];
export const D2_ASSISTED_REVIEW = ['@flow:d2-assisted-review', '@module:review', '@priority:P1'];
export const D3_ANCHORED_OBSERVATIONS = ['@flow:d3-anchored-observations', '@module:review', '@priority:P1'];
export const D4_SEAL_APPROVE = ['@flow:d4-seal-approve', '@module:review', '@priority:P1'];
export const D5_SELECTIVE_INVALIDATION = ['@flow:d5-selective-invalidation', '@module:review', '@priority:P1'];
export const E4_CONSTANCIA = ['@flow:e4-constancia', '@module:review', '@priority:P2'];
