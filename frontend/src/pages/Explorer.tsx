import { useCallback, useEffect, useRef, useState } from 'react'
import { api, downloadBlob } from '../api'
import { useTenant } from '../App'
import { Btn, useToast } from '../ui'

// O Explorer é o DocViva (public/viewer) em modo incorporado: recebe o inventário por postMessage
// e devolve anotações, documentação e pedidos de PDF, que esta página grava pela API.
export default function Explorer() {
  const { tenant } = useTenant()
  const frame = useRef<HTMLIFrameElement>(null)
  const toast = useToast()
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errMsg, setErrMsg] = useState('')

  const send = useCallback(async () => {
    setState('loading')
    setErrMsg('')
    try {
      const inv = await api(`/api/tenants/${tenant.id}/inventory`)
      frame.current?.contentWindow?.postMessage({ type: 'docops:load', ...inv }, location.origin)
      setState('ready')
    } catch (e: any) {
      setErrMsg(e.message || 'Falha ao carregar o inventário.')
      setState('error')
      toast(e.message, 'err')
    }
  }, [tenant.id, toast])

  useEffect(() => {
    const onMsg = async (e: MessageEvent) => {
      if (e.origin !== location.origin || e.source !== frame.current?.contentWindow) return
      const d = e.data || {}
      if (d.type === 'docops:ready') send()
      if (d.type === 'docops:save') {
        try {
          if (d.notes) await api(`/api/tenants/${tenant.id}/notes`, { method: 'PUT', body: { changes: d.notes } })
          if (d.docs) await api(`/api/tenants/${tenant.id}/docs`, { method: 'PUT', body: { data: d.docs } })
        } catch (x: any) { toast(`Não foi possível salvar: ${x.message}`, 'err') }
      }
      if (d.type === 'docops:pdf') {
        try {
          const r = await api<Response>(`/api/tenants/${tenant.id}/reports/pdf`, { body: { html: d.html, filename: d.filename }, raw: true })
          downloadBlob(await r.blob(), d.filename)
          toast('PDF gerado')
        } catch (x: any) { toast(x.message, 'err') }
      }
    }
    window.addEventListener('message', onMsg)
    return () => { window.removeEventListener('message', onMsg) }
  }, [tenant.id, toast, send])

  return (
    <div className="explorer">
      {state === 'loading' && <div className="explorer-loading"><span className="spin dark" /> Carregando inventário…</div>}
      {state === 'error' && (
        <div className="explorer-loading">
          <div className="empty">
            <b>Não foi possível carregar o Explorer</b>
            <p className="muted">{errMsg}</p>
            <Btn kind="primary" onClick={send}>Tentar novamente</Btn>
          </div>
        </div>
      )}
      <iframe ref={frame} title="Explorer" src="/viewer/index.html?embed=1" />
    </div>
  )
}
