import React, { useRef, useState } from 'react'
import { Spinner, TemplateLink, Icon } from './ui.jsx'

export function UploadDropzone({ onUpload, busy }) {
  const inputRef = useRef()
  const [drag, setDrag] = useState(false)
  const [name, setName] = useState(null)

  function handle(file) {
    if (!file) return
    setName(file.name)
    onUpload(file)
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={e => { e.preventDefault(); setDrag(false); handle(e.dataTransfer.files[0]) }}
      onClick={() => inputRef.current?.click()}
      className={`card p-6 cursor-pointer text-center transition-colors ${drag ? 'border-lime bg-lime/5' : 'border-dashed'}`}
    >
      <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" hidden
        onChange={e => handle(e.target.files[0])} />
      {busy ? <Spinner label="ingesting bulk file…" /> : (
        <div className="font-mono text-sm">
          <div className="text-lime text-lg mb-1 inline-flex items-center gap-1"><Icon name="upload" size={20} /> drop SP bulk .xlsx / .csv</div>
          <div className="text-mute">{name || 'or click to browse — Amazon Sponsored Products bulk export'}</div>
          <div className="mt-2"><TemplateLink kind="bulk" label="download template format" /></div>
        </div>
      )}
    </div>
  )
}

export function TargetAcosControl({ value, onChange }) {
  // ROAS is the reciprocal of ACoS (sales per ad-$). Editing either updates goal.
  const roas = value ? 1 / value : 0
  // buffer raw text while typing so the field doesn't fight mid-entry; revert to derived on blur
  const [buf, setBuf] = useState(null)
  const shown = buf != null ? buf : roas.toFixed(2)
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-mute text-[11px] font-mono uppercase tracking-wider">Goal ACoS</span>
        <span className="font-mono text-lime text-lg font-bold">{(value * 100).toFixed(0)}%</span>
      </div>
      <input type="range" min="5" max="80" step="1" value={value * 100}
        onChange={e => onChange(Number(e.target.value) / 100)}
        className="w-full accent-lime" />
      <div className="flex justify-between text-[10px] font-mono text-mute mt-1">
        <span>5%</span><span>aggressive ← → loose</span><span>80%</span>
      </div>
      <div className="flex items-center justify-between mt-3 pt-3 border-t border-edge">
        <span className="text-mute text-[11px] font-mono uppercase tracking-wider">Goal ROAS</span>
        <div className="flex items-center gap-1">
          <input value={shown} inputMode="decimal"
            onChange={e => { setBuf(e.target.value); const r = parseFloat(e.target.value); if (r > 0) onChange(1 / r) }}
            onBlur={() => setBuf(null)}
            className="bg-panel border border-edge rounded px-2 py-1 font-mono text-sm text-cyan w-16 text-right focus:outline-none focus:border-cyan" />
          <span className="font-mono text-cyan text-sm font-bold">×</span>
        </div>
      </div>
    </div>
  )
}
