'use client';

/** A2 — members + invitations management (project settings, admin). */

import { useCallback, useEffect, useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { api } from '@/lib/services/http';
import { maybeShowUpgradeDialog } from '@/lib/stores/upgradeDialogStore';
import { useReviewStore } from '@/lib/stores/reviewStore';

interface InvitationRow {
  public_id: string;
  email: string;
  role: string;
  status: 'pending' | 'accepted' | 'revoked';
  invited_by: string;
  created_at: string;
}

const ROLES = ['viewer', 'reviewer', 'editor', 'admin'] as const;

export function MembersSection({ projectId }: { projectId: string }) {
  const t = useDict('invitations');
  const projects = useDict('projects');
  const common = useDict('common');
  const { toast } = useToast();
  const members = useReviewStore((s) => s.members);
  const fetchMembers = useReviewStore((s) => s.fetchMembers);
  const [invitations, setInvitations] = useState<InvitationRow[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<string>('reviewer');

  const load = useCallback(async () => {
    void fetchMembers(projectId);
    try {
      const { data } = await api.get(`projects/${projectId}/invitations/`);
      setInvitations(data.results);
    } catch {
      // non-admins never reach this section
    }
  }, [projectId, fetchMembers]);

  useEffect(() => {
    void load();
  }, [load]);

  const invite = async () => {
    try {
      await api.post(`projects/${projectId}/invitations/`, { email: email.trim(), role });
      toast(common.saved, 'success');
      setEmail('');
      void load();
    } catch (err) {
      if (maybeShowUpgradeDialog(err)) return;
      toast(
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
          common.error,
        'error'
      );
    }
  };

  return (
    <section data-testid="members-section" className="mt-10">
      <h2 className="text-lg font-semibold">{t.membersTitle}</h2>

      <ul className="mt-3 flex flex-col gap-1.5">
        {members.map((member) => (
          <li
            key={member.id}
            className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-border bg-card px-3 py-2 text-sm sm:items-center"
          >
            <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">{member.email}</span>
            <StatusBadge variant="neutral">
              {projects.role[member.role as keyof typeof projects.role] ?? member.role}
            </StatusBadge>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="block min-w-0 flex-[1_1_12rem] text-sm">
          <span className="text-muted-foreground">{t.email}</span>
          <input
            data-testid="invite-email"
            className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">{t.role}</span>
          <select
            data-testid="invite-role"
            className="mt-1 min-h-11 rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {ROLES.map((option) => (
              <option key={option} value={option}>
                {projects.role[option]}
              </option>
            ))}
          </select>
        </label>
        <button
          data-testid="send-invite"
          className="min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
          disabled={!email.trim()}
          onClick={() => void invite()}
          type="button"
        >
          {t.invite}
        </button>
      </div>

      {invitations.length > 0 ? (
        <ul data-testid="invitations-list" className="mt-4 flex flex-col gap-1.5">
          {invitations.map((invitation) => (
            <li
              key={invitation.public_id}
              className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-dashed border-border px-3 py-2 text-sm sm:items-center"
            >
              <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">
                {invitation.email}
                <span className="ml-2 text-xs text-muted-foreground">
                  ({projects.role[invitation.role as keyof typeof projects.role] ?? invitation.role})
                </span>
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge
                  variant={
                    invitation.status === 'accepted'
                      ? 'approved'
                      : invitation.status === 'revoked'
                        ? 'failed'
                        : 'draft'
                  }
                >
                  {t[invitation.status as 'pending' | 'accepted' | 'revoked']}
                </StatusBadge>
                {invitation.status === 'pending' ? (
                  <button
                    data-testid={`revoke-${invitation.email}`}
                    className="min-h-11 min-w-11 text-sm text-destructive underline-offset-2 hover:underline"
                    onClick={() =>
                      void api
                        .post(`projects/${projectId}/invitations/${invitation.public_id}/revoke/`)
                        .then(() => load())
                    }
                    type="button"
                  >
                    {t.revoke}
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
