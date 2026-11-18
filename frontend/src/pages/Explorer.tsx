import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, downloadBlob, fmtDT } from '../api'
import { useTenant } from '../App'
import { Btn, Pill, useToast } from '../ui'

interface VersionItem {
  id: number
  account_id: string
  alias: string
  source: string
  trigger: string
  collected_at: string | null
  created_at: string
}

// O Explorer é o DocViva (public/viewer) em modo incorporado: recebe o inventário por postMessage
// e devolve anotações, documentação e pedidos de PDF, que esta página grava pela API.
export default function Explorer() {
  const { tenant } = useTenant()
  const [searchParams, setSearchParams] = useSearchParams()
  const frame = useRef<HTMLIFrameElement>(null)
  const readyRef = useRef(false)
  const toast = useToast()

  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errMsg, setErrMsg] = useState('')
  const [versions, setVersions] = useState<Record<string, VersionItem[]>>({})
  const [selected, setSelected] = useState<Record<string, number>>({})
  const [isHistorical, setIsHistorical] = useState(false)

  const initialColId = searchParams.get('collection_id')

  const loadInventory = useCallback(async (overrideIds?: number[], singleColId?: string | null) => {
    setState('loading')
    setErrMsg('')
    try {
      const qs = overrideIds?.length
        ? `?collection_ids=${overrideIds.join(',')}`
        : singleColId
          ? `?collection_id=${encodeURIComponent(singleColId)}`
          : ''
      const inv = await api(`/api/tenants/${tenant.id}/inventory${qs}`)
      const vMap: Record<string, VersionItem[]> = inv.versions || {}
      setVersions(vMap)

      const activeMap: Record<string, number> = {}
      for (const c of inv.collections || []) {
        activeMap[c.account_id] = c.id
      }
      setSelected(activeMap)

      const anyHistorical = Object.entries(activeMap).some(([accId, cid]) => {
        const list = vMap[accId] || []
        return list.length > 0 && list[0].id !== cid
      })
      setIsHistorical(anyHistorical)

      if (readyRef.current) {
        frame.current?.contentWindow?.postMessage({ type: 'docops:load', ...inv }, location.origin)
      }
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
      if (d.type === 'docops:ready') {
        readyRef.current = true
        loadInventory(undefined, initialColId)
      }
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
  }, [tenant.id, toast, loadInventory, initialColId])

  const changeAccountVersion = (accountId: string, colId: number) => {
    const next = { ...selected, [accountId]: colId }
    setSelected(next)
    if (searchParams.has('collection_id')) setSearchParams({}, { replace: true })
    loadInventory(Object.values(next))
  }

  const resetToLatest = () => {
    if (searchParams.has('collection_id')) setSearchParams({}, { replace: true })
    loadInventory()
  }

  const accountsWithHistory = Object.entries(versions).filter(([, list]) => list.length > 1)
  const showBar = accountsWithHistory.length > 0 || isHistorical

  return (
    <div className="explorer">
      {showBar && (
        <div className={`timeline-bar ${isHistorical ? 'hist' : ''}`}>
          <span className="tl-lbl">
            {isHistorical ? <Pill kind="warn">Levantamento histórico</Pill> : <Pill kind="ok">Versão atual</Pill>}
            <span>Linha do tempo:</span>
          </span>
          <div className="tl-selects">
            {Object.entries(versions).map(([accId, list]) => {
              if (list.length <= 1 && (!selected[accId] || selected[accId] === list[0]?.id)) return null
              const cur = selected[accId] || list[0]?.id
              return (
                <label key={accId} className="tl-item">
                  <span>{list[0]?.alias || accId}</span>
                  <select value={cur} onChange={(e) => changeAccountVersion(accId, Number(e.target.value))}>
                    {list.map((v, idx) => {
                      const tag = idx === 0 ? 'Atual' : `v${list.length - idx}`
                      const src = v.source === 'upload' ? 'manual' : 'automática'
                      return (
                        <option key={v.id} value={v.id}>
                          {tag} · {fmtDT(v.collected_at || v.created_at)} ({src})
                        </option>
                      )
                    })}
                  </select>
                </label>
              )
            })}
          </div>
          {isHistorical && <Btn small kind="primary" onClick={resetToLatest}>Voltar ao levantamento atual</Btn>}
        </div>
      )}

      <div className="explorer-frame-wrap">
        {state === 'loading' && <div className="explorer-loading"><span className="spin dark" /> Carregando inventário…</div>}
        {state === 'error' && (
          <div className="explorer-loading">
            <div className="empty">
              <b>Não foi possível carregar o Explorer</b>
              <p className="muted">{errMsg}</p>
              <Btn kind="primary" onClick={() => loadInventory(Object.values(selected))}>Tentar novamente</Btn>
            </div>
          </div>
        )}
        <iframe ref={frame} title="Explorer" src="/viewer/index.html?embed=1" />
      </div>
    </div>
  )
}
