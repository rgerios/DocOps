import { useState } from 'react'
import { api, fmtDT, ROLE_LABEL } from '../api'
import { useSession } from '../App'
import { Btn, Card, Field, PageHead, Pill, Secret, useConfirm, useToast } from '../ui'

export default function MyAccount() {
  const { me, setMe } = useSession()
  const toast = useToast()
  const confirm = useConfirm()
  const [cur, setCur] = useState('')
  const [n1, setN1] = useState('')
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null)
  const [code, setCode] = useState('')
  const [dis, setDis] = useState({ password: '', code: '' })
  const changePwd = async () => {
    try { setMe(await api('/api/auth/password', { body: { current: cur, new: n1 } })); setCur(''); setN1(''); toast('Senha alterada') } catch (e: any) { toast(e.message, 'err') }
  }
  const startMfa = async () => { try { setSetup(await api('/api/auth/mfa/setup', { method: 'POST' })) } catch (e: any) { toast(e.message, 'err') } }
  const enableMfa = async () => { try { setMe(await api('/api/auth/mfa/enable', { body: { code } })); setSetup(null); setCode(''); toast('MFA ativado') } catch (e: any) { toast(e.message, 'err') } }
  const disableMfa = async () => { try { setMe(await api('/api/auth/mfa/disable', { body: dis })); setDis({ password: '', code: '' }); toast('MFA desativado', 'info') } catch (e: any) { toast(e.message, 'err') } }
  const logoutAll = async () => { if (await confirm({ title: 'Encerrar sessões', message: 'Encerrar a sessão em todos os navegadores, inclusive este?', confirmLabel: 'Encerrar todas' })) { await api('/api/auth/logout-all', { method: 'POST' }); setMe(null) } }
  return (
    <div className="page narrow">
      <PageHead title="Minha conta" sub={`${me.name} · ${me.email}${me.last_login ? ` · último acesso ${fmtDT(me.last_login)}` : ''}`} />
      <Card title="Autenticação em dois fatores (MFA)" actions={me.totp_enabled ? <Pill kind="ok">ativo</Pill> : <Pill kind="warn">desativado</Pill>}>
        {!me.totp_enabled && !setup && <><p className="small">Proteja sua conta com um aplicativo autenticador (Google Authenticator, Microsoft Authenticator, 1Password…).</p><Btn kind="primary" onClick={startMfa}>Configurar MFA</Btn></>}
        {setup && <div className="mfa">
          <img src={setup.qr} alt="QR code do MFA" />
          <div>
            <p className="small">1. Escaneie o QR code no aplicativo autenticador (ou digite a chave abaixo).</p>
            <Secret label="Chave" value={setup.secret} />
            <p className="small">2. Digite o código de 6 dígitos que aparece no aplicativo:</p>
            <div className="row"><input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} maxLength={8} placeholder="000000" /><Btn kind="primary" onClick={enableMfa}>Ativar</Btn></div>
          </div>
        </div>}
        {me.totp_enabled && <div className="row">
          <input type="password" placeholder="Senha" value={dis.password} onChange={(e) => setDis({ ...dis, password: e.target.value })} />
          <input inputMode="numeric" placeholder="Código MFA" value={dis.code} onChange={(e) => setDis({ ...dis, code: e.target.value })} />
          <Btn kind="danger" onClick={disableMfa}>Desativar MFA</Btn>
        </div>}
      </Card>
      <Card title="Trocar senha">
        <div className="grid2">
          <Field label="Senha atual"><input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field>
          <Field label="Nova senha" hint="Mínimo de 12 caracteres, com letras, números e símbolos."><input type="password" autoComplete="new-password" value={n1} onChange={(e) => setN1(e.target.value)} /></Field>
        </div>
        <div className="row"><Btn kind="primary" onClick={changePwd}>Alterar senha</Btn><Btn kind="ghost" onClick={logoutAll}>Encerrar todas as sessões</Btn></div>
      </Card>
      <Card title="Meus acessos">
        {me.is_superadmin && <p><Pill kind="lav">Administrador da plataforma</Pill> acesso total a todos os clientes.</p>}
        {me.tenants.map((t) => <p key={t.id} className="small"><b>{t.name}</b> — {ROLE_LABEL[t.role]}</p>)}
      </Card>
    </div>
  )
}
