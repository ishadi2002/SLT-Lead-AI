import React, { useState } from 'react';
import { UploadCloud, Download, Search, GraduationCap, BriefcaseBusiness, Wifi, FileSpreadsheet, ShieldCheck, CheckCircle2, AlertTriangle } from 'lucide-react';
const BASE = 'http://127.0.0.1:8000';
const categoryDefs = [
  {key:'education',name:'Education',icon:GraduationCap,desc:'CAIT · HND · UH'},
  {key:'business',name:'Business',icon:BriefcaseBusiness,desc:'SME · Business connectivity'},
  {key:'broadband',name:'Broadband',icon:Wifi,desc:'Residential · Galle Geo'},
];
export default function App(){
 const [category,setCategory] = useState('education');
 const [file,setFile] = useState(null);
 const [result,setResult] = useState(null);
 const [busy,setBusy] = useState(false);
 const [error,setError] = useState('');
 const [query,setQuery] = useState('');
 const [showOriginal,setShowOriginal] = useState(false);
 const [sheet,setSheet] = useState('all');
 const reset = () => {setFile(null);setResult(null);setError('');setQuery('');setSheet('all');};
 async function analyze(e){
  e.preventDefault(); if(!file) return setError('Please choose an Excel (.xlsx) file.');
  setBusy(true);setError('');setResult(null);setSheet('all');
  const body = new FormData();body.append('category',category);body.append('file',file);
  try{
   const r=await fetch(`${BASE}/api/analyze`,{method:'POST',body});
   const json=await r.json();if(!r.ok) throw Error(json.detail || 'Analysis failed');setResult(json);
  }catch(e){setError(e.message+' — make sure FastAPI is running.');}
  finally{setBusy(false);}
 }
 function download(){if(result) window.location.href = `${BASE}/api/export/${result.analysis_id}`;}
 const sheets = [...new Set((result?.rows||[]).map(x=>x.sheet))];
 const shown=(result?.rows||[]).filter(row=>
  (sheet==='all'||row.sheet===sheet)&&[row.name,row.phone,row.reason,...Object.values(row.original)].join(' ').toLowerCase().includes(query.toLowerCase())
 );
 const columns= [...new Set(shown.flatMap(x=>Object.keys(x.original)))];
 return <div className="page"><header className="topbar"><div className="brandmark">SLT</div><div><strong>Lead Qualification</strong><div className="subtle">Meta Campaign Lead Review</div></div><span className="topright">LOCAL ANALYSIS · NO EXTERNAL UPLOADS</span></header>
 <main className="content"><div className="intro"><div><div className="eyebrow">CAMPAIGN INTELLIGENCE</div><h1>Find your best leads.</h1><p>Upload a weekly Excel file, choose the campaign category, and export top leads with their original details and clear selection reasons.</p></div><div className="introicon"><ShieldCheck size={32}/></div></div>
 <form onSubmit={analyze} className="panel"><div className="sectiontitle"><span className="number">01</span> Select campaign category</div><div className="categorygrid">{categoryDefs.map(d=>{const I=d.icon;return <button type="button" key={d.key} className={'category '+(category===d.key?'active':'')} onClick={()=>{setCategory(d.key);reset();}}><I size={22}/><strong>{d.name}</strong><small>{d.desc}</small></button>})}</div>
 <div className="sectiontitle mt"><span className="number">02</span> Upload weekly Excel workbook</div><label className="dropzone"><UploadCloud size={30}/><span className="filetitle">{file?file.name:'Choose .xlsx file to analyze'}</span><small>Excel file up to 15 MB • All source worksheets supported</small><input type="file" accept=".xlsx" onChange={e=>{setFile(e.target.files?.[0]||null);setResult(null);setError('');}}/></label>
 <div className="actionbar"><span className="subtle">Only qualified leads will appear in the downloadable file.</span><button type="submit" disabled={busy||!file} className="primary"><Search size={17}/>{busy?'Analyzing…':'Find Top Leads'}</button></div>{error&&<div role="alert" className="alert"><AlertTriangle size={17}/>{error}</div>}</form>
 {result && <section className="panel results"><div className="resulthead"><div><div className="sectiontitle"><span className="number">03</span> Top lead results</div><p className="subtle">Original Excel fields are preserved. No scores are displayed.</p></div><button className="download" onClick={download}><Download size={18}/> Download Excel</button></div>
 <div className="metrics"><div><small>Rows analyzed</small><strong>{result.total_rows}</strong></div><div><small>Unique leads</small><strong>{result.unique_rows}</strong></div><div className="topmetric"><small>Top leads selected</small><strong>{result.top_leads}</strong></div><div><small>Not selected</small><strong>{result.excluded_rows}</strong></div></div>
 {!!result.warnings.length&&<div className="warning">{result.warnings.map((w,i)=><div key={i}>⚠ {w}</div>)}</div>}
 <div className="filters"><input aria-label="Search results" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search student/customer, phone, feedback…"/><select aria-label="Filter worksheet" value={sheet} onChange={e=>setSheet(e.target.value)}><option value="all">All sheets</option>{sheets.map(s=><option key={s}>{s}</option>)}</select><label className="toggle"><input type="checkbox" checked={showOriginal} onChange={e=>setShowOriginal(e.target.checked)}/> Show all original columns</label></div>
 <div className="tablewrap"><table><thead><tr>{showOriginal?<>{columns.map(c=><th key={c}>{c}</th>)}<th>Why Top Lead?</th></>:<><th>Source</th><th>Name</th><th>Phone</th><th>Original feedback</th><th>Why Top Lead?</th></>}</tr></thead><tbody>{shown.map((r,i)=><tr key={`${r.sheet}-${r.row}-${i}`}>{showOriginal?<>{columns.map(c=><td key={c}>{r.original[c]||'—'}</td>)}<td className="reason">{r.reason}</td></>:<><td><span className="pill">{r.sheet}</span></td><td>{r.name}</td><td className="mono">{r.phone||'—'}</td><td>{['Customer Feedback','Feedback','Column G','Column H','Column I','2nd Call Remarks'].map(k=>r.original[k]).filter(Boolean).join(' | ')||'—'}</td><td className="reason">{r.reason}</td></>}</tr>)}</tbody></table>{shown.length===0&&<div className="empty">No leads match this filter. If no top leads were found, review source feedback and qualification criteria.</div>}</div><p className="fineprint"><CheckCircle2 size={14}/> Results use separate evidence-based rules per category. Historical leads require fresh follow-up verification.</p></section>}
 <footer>SLT Lead Qualification MVP · Local processing · Review AI/rule recommendations before contacting customers</footer></main></div>
}
