import { useState } from 'react'
import { api, fmtDT } from '../api'
import { useTenant } from '../App'
import { Card, ErrorBox, PageHead, useLoad } from '../ui'

export const ACTIONS: Record<string, string> = {
  'login.ok': 'Login', 'login.failed': 'Login falhou', 'login.locked': 'Conta bloqueada', 'password.changed': 'Senha alterada',
  'mfa.enabled': 'MFA ativado', 'mfa.disabled': 'MFA desativado', 'logout.all': 'Encerrou todas as sessões',
  'tenant.created': 'Cliente criado', 'tenant.updated': 'Cliente alterado', 'tenant.deleted': 'Cliente excluído',
  'member.added': 'Acesso concedido', 'member.role': 'Perfil alterado', 'member.removed': 'Acesso removido',
  'user.created': 'Usuário criado', 'user.updated': 'Usuário alterado', 'user.password_reset': 'Senha redefinida', 'user.mfa_reset': 'MFA redefinido',
  'account.created': 'Conta AWS cadastrada', 'account.updated': 'Conta AWS alterada', 'account.deleted': 'Conta AWS removida',
  'collection.started': 'Coleta disparada', 'collection.started_all': 'Coleta de todas as contas', 'collection.uploaded': 'Arquivo importado',
  'collection.deleted': 'Coleta excluída', 'collection.downloaded': 'JSON baixado', 'notes.saved': 'Anotações/tratativas salvas',
  'docs.saved': 'Documentação salva', 'schedule.created': 'Agendamento criado', 'schedule.updated': 'Agendamento alterado',
  'schedule.deleted': 'Agendamento excluído', 'settings.updated': 'Alertas configurados', 'report.pdf': 'Relatório PDF gerado',
}

export function AuditTable({ rows }: { rows: any[] }) {
  const [q, setQ] = useState('')
  const f = rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()))
  return (
    <>
      <div className="pad"><input placeholder="Filtrar por pessoa, ação, conta…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <table className="t compact">
        <thead><tr><th>Quando</th><th>Pessoa</th><th>Ação</th><th>Detalhe</th><th>IP</th></tr></thead>
        <tbody>{f.map((r) => (
          <tr key={r.id}><td className="small nowrap">{fmtDT(r.at)}</td><td className="small">{r.user || '—'}</td><td>{ACTIONS[r.action] || r.action}</td>
            <td className="small mono detail">{r.detail ? Object.entries(r.detail).filter(([, v]) => v !== null).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ') : ''}</td>
            <td className="small mono">{r.ip}</td></tr>))}
        </tbody>
      </table>
    </>
  )
}

export default function Audit() {
  const { tenant } = useTenant()
  const { data, error } = useLoad<any[]>(() => api(`/api/tenants/${tenant.id}/audit?limit=1000`), [tenant.id])
  return (
    <div className="page">
      <PageHead title="Auditoria" sub="Quem fez o quê neste cliente: coletas, alterações, acessos e tratativas." />
      <ErrorBox error={error} />
      <Card pad={false}>{data ? <AuditTable rows={data} /> : <div className="pad muted">Carregando…</div>}</Card>
    </div>
  )
}
