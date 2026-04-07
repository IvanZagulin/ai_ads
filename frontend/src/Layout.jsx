import { useState, useEffect, useCallback } from 'react';

const navItems = [
  { hash: '#/', label: 'Dashboard', icon: 'LayoutDashboard' },
  { hash: '#/accounts', label: 'Аккаунты', icon: 'Users' },
  { hash: '#/campaigns', label: 'Кампании', icon: 'Megaphone' },
  { hash: '#/decisions', label: 'Решения', icon: 'Brain' },
  { hash: '#/actions', label: 'Действия', icon: 'CheckCircle' },
];

function Icon({ name, size = 20, style }) {
  const icons = {
    LayoutDashboard: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>,
    Users: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
    Megaphone: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>,
    Brain: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4 0 0 1-3-4 4.5 4 0 0 1-3 4"/><path d="M17.599 6.843a2 2 0 0 1 2.612 1.149"/><path d="M3.789 8.334a2 2 0 0 1 2.8-1.79"/></svg>,
    CheckCircle: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M9 11l3 3L22 4"/></svg>,
    HeartPulse: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="M19 14c1.48-1.43 3-3.21 3-5.68A4.35 4.35 0 0 0 20.5 5 4.7 4.7 0 0 0 17 3c-2 0-3.5 1-5 3-1.5-2-3-3-5-3A4.7 4.7 0 0 0 3.5 8.32c0 2.47 1.52 4.25 3 5.68L12 22l7-8Z"/><path d="M6 9.5a2 2 0 0 0 1.964 1.642L12 9l4 2 3.5-2.5"/></svg>,
    Sun: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>,
    Moon: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>,
    Menu: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/></svg>,
    Zap: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>,
  };
  return icons[name] || null;
}

export default function Layout({ children, title }) {
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem('theme-ads') === 'dark'; } catch { return false; }
  });
  const [hash, setHash] = useState(window.location.hash || '#/');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [healthy, setHealthy] = useState(null);

  useEffect(() => {
    const handler = () => setHash(window.location.hash || '#/');
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try { localStorage.setItem('theme-ads', dark ? 'dark' : 'light'); } catch {}
  }, [dark]);

  useEffect(() => {
    fetch('/api/health').then(r => r.json()).then(() => setHealthy(true)).catch(() => setHealthy(false));
  }, [hash]);

  const pageTitle = title || navItems.find(n => {
    if (n.hash === '#/') return hash === '#/' || hash === '';
    return hash.startsWith(n.hash);
  })?.label || 'AI Ads Manager';

const triggerLabel = 'Запустить оптимизацию';
  const handleTrigger = useCallback(async () => {
    try {
      const data = await fetch('/api/analysis/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).then(r => r.json());
      alert(data.message || 'Цикл запущен');
    } catch (e) {
      alert('Ошибка: ' + e.message);
    }
  }, []);

  return (
    <div className="flex min-h-screen bg-background">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ── SIDEBAR ─────────────────────────────────────────────── */}
      <aside className={`fixed inset-y-0 left-0 z-50 flex w-60 flex-col bg-sidebar border-r border-sidebar-border transition-transform duration-200 lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 px-4 border-b border-sidebar-border">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-lg flex-shrink-0"
            style={{
              background: 'linear-gradient(135deg, var(--neon), var(--accent-blue))',
              boxShadow: '0 2px 12px rgba(0,200,255,.3)',
            }}
          >
            <span className="w-2 h-2 rounded-full bg-white" />
          </div>
          <span className="font-mono text-sm font-bold tracking-wider text-foreground flex-1">AI ADS</span>
          <button className="lg:hidden p-1 text-muted-foreground hover:text-foreground" onClick={() => setSidebarOpen(false)}>
            <Icon name="Menu" size={18} />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {navItems.map(item => {
            const active = item.hash === '#/' ? (hash === '#/' || hash === '') : hash.startsWith(item.hash);
            return (
              <a
                key={item.hash}
                href={item.hash}
                className="sidebar-link"
                style={active ? { background: 'var(--neon-glow)', color: 'var(--neon)', fontWeight: 600, borderLeft: '3px solid var(--neon)' } : {}}
                onClick={() => setSidebarOpen(false)}
              >
                <Icon name={item.icon} size={18} style={active ? { color: 'var(--neon)' } : {}} />
                {item.label}
              </a>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="space-y-0.5 p-3 border-t border-sidebar-border">
          <div className="flex items-center gap-2 rounded-[10px] px-3 py-2">
            <span
              className={`h-2 w-2 rounded-full flex-shrink-0`}
              style={{ background: healthy ? 'var(--neon)' : '#ef4444', boxShadow: healthy ? '0 0 8px var(--neon-dim)' : '0 0 8px rgba(239,68,68,.3)' }}
            />
            <span className="text-xs text-muted-foreground">{healthy ? 'Система активна' : 'API не доступен'}</span>
          </div>

          <div className="my-1.5 h-px bg-border" />

          <button className="btn btn-primary w-full text-sm" onClick={handleTrigger}>
            <Icon name="Zap" size={16} />
            Оптимизация
          </button>

          <button
            className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2 text-sm font-medium text-muted-foreground transition-all hover:text-foreground"
            onClick={() => setDark(!dark)}
          >
            <Icon name={dark ? 'Sun' : 'Moon'} size={18} />
            <span>{dark ? 'Светлая тема' : 'Тёмная тема'}</span>
          </button>
        </div>
      </aside>

      {/* ── MAIN ───────────────────────────────────────────────── */}
      <div className="flex-1 lg:ml-60 flex flex-col">
        {/* Mobile menu button */}
        <button
          className="lg:hidden fixed top-3 left-3 z-40 rounded-lg bg-card border border-border p-2 shadow-sm"
          onClick={() => setSidebarOpen(true)}
        >
          <Icon name="Menu" size={20} />
        </button>

        {/* Header */}
        <header className="h-14 border-b border-border bg-card/50 backdrop-blur-sm flex items-center justify-end px-4 lg:px-6">
          <span className="flex items-center gap-1.5 text-xs lg:hidden">
            <span className={`glow-dot`} style={{ background: healthy ? 'var(--neon)' : '#ef4444', boxShadow: healthy ? '0 0 8px var(--neon-dim)' : '0 0 8px rgba(239,68,68,.3)' }} />
            <span className="text-muted-foreground">{healthy ? 'API OK' : 'API'}</span>
          </span>
        </header>

        <main className="flex-1 p-8 pt-12 lg:pt-8 animate-fade-in-up">
          {children}
        </main>
      </div>
    </div>
  );
}
