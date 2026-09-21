import './page-header.css'

export default function PageHeader({ title, back }: { title: string; back: string }) {
  return <header className="subpage-header">
    <div className="subpage-header-row">
      <a className="subpage-back" href={`#${back}`} aria-label="返回上一页" title="返回上一页">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m14 6-6 6 6 6" /></svg>
      </a>
      <h1>{title}</h1>
    </div>
  </header>
}
