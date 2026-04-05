import { useState, useEffect, useCallback } from 'react';

const navItems = [
  { hash: '#/', label: 'Dashboard', icon: 'LayoutDashboard' },
  { hash: '#/accounts', label: 'Аккаунты', icon: 'Users' },
  { hash: '#/campaigns', label: 'Кампании', icon: 'Megaphone' },
  { hash: '#/decisions', label: 'Решения', icon: 'Brain' },
  { hash: '#/actions', label: 'Действия', icon: 'CheckCircle' },
];

function Icon({ name, size = 20 }) {
  const icons = {
    LayoutDashboard: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>,
    Users: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
    Megaphone: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>,
    Brain: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4 0 0 1-3-4 4.5 4 0 0 1-3 4"/><path d="M17.599 6.843a2 2 0 0 1 2.612 1.149"/><path d="M3.789 8.334a2 2 0 0 1 2.8-1.79"/></svg>,
    CheckCircle: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M9 11l3 3L22 4"/></svg>,
    Sun: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>,
    Moon: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>,
    Menu: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/></svg>,
    Zap: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>,
    HeartPulse: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 14c1.48-1.43 3-3.21 3-5.68A4.35 4.35 0 0 0 20.5 5 4.7 4.7 0 0 0 17 3c-2 0-3.5 1-5 3-1.5-2-3-3-5-3A4.7 4.7 0 0 0 3.5 8.32c0 2.47 1.52 4.25 3 5.68L12 22l7-8Z"/><path d="M6 9.5a2 2 0 0 0 1.964 1.642L12 9l4 2 3.5-2.5"/></svg>,
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
      {/* Sidebar overlay mobile */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`fixed inset-y-0 left-0 z-40 w-64 bg-sidebar border-r border-sidebar-border flex flex-col transition-transform duration-200 lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="p-5 flex items-center gap-3">
          <Icon name="Zap" size={24} />
          <div>
            <div className="text-sm font-bold text-foreground" style={{ color: 'var(--neon)' }}>AI ADS</div>
            <div className="text-xs text-muted-foreground">Manager</div>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {navItems.map(item => {
            const active = item.hash === '#/' ? (hash === '#/' || hash === '') : hash.startsWith(item.hash);
            return (
              <a key={item.hash} href={item.hash} className={`sidebar-link ${active ? 'active' : ''}`} onClick={() => setSidebarOpen(false)}>
                <Icon name={item.icon} size={18} />
                {item.label}
              </a>
            );
          })}
        </nav>

        <div className="p-3">
          <button className="btn btn-primary w-full text-sm" onClick={handleTrigger}>
            <Icon name="Zap" size={16} />
            Оптимизация
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 lg:ml-64 flex flex-col">
        <header className="h-14 border-b border-border bg-card/50 backdrop-blur-sm flex items-center justify-between px-4 lg:px-6">
          <div className="flex items-center gap-3">
            <button className="lg:hidden" onClick={() => setSidebarOpen(true)}>
              <Icon name="Menu" size={22} />
            </button>
            <h1 className="text-lg font-semibold text-foreground">{pageTitle}</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs">
              <span className={`glow-dot ${healthy ? '' : 'opacity-30'}`} style={{ background: healthy ? 'var(--neon)' : '#ef4444', boxShadow: healthy ? '0 0 8px var(--neon-dim)' : '0 0 8px rgba(239,68,68,.3)' }} />
              <span className="text-muted-foreground">{healthy ? 'API OK' : 'API'}</span>
            </span>
            <button className="p-2 rounded-lg hover:bg-accent transition-colors" onClick={() => setDark(!dark)} title={dark ? 'Светлая тема' : 'Тёмная тема'}>
              <Icon name={dark ? 'Sun' : 'Moon'} size={18} />
            </button>
          </div>
        </header>
        <main className="flex-1 p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
