import { useState, useEffect, useCallback } from 'react';
import Layout from './Layout';
import { api } from './api';

// ── Helpers ──

function Badge({ children, variant = 'info' }) {
  const cls = { success: 'badge-success', warning: 'badge-warning', error: 'badge-error', info: 'badge-info' }[variant] || 'badge-info';
  return <span className={`badge ${cls}`}>{children}</span>;
}

function statusBadge(s) {
  const map = { active: 'success', paused: 'warning', completed: 'info', cancelled: 'error', deleted: 'error' };
  return <Badge variant={map[s] || 'info'}>{s}</Badge>;
}

function platformBadge(p) {
  return <Badge variant={p === 'wildberries' ? 'info' : 'success'}>{p === 'wildberries' ? 'WB' : 'Ozon'}</Badge>;
}

function Sparkline({ data, color = 'var(--neon)' }) {
  if (!data || data.length < 2) return null;
  const w = 60, h = 20, pad = 1;
  const max = Math.max(...data, 1), min = Math.min(...data, 0);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / range) * (h - 2 * pad);
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'inline-block', verticalAlign: 'middle' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Pages ──

function DashboardPage() {
  const [stats, setStats] = useState({ campaigns: 0, accounts: 0, decisions: 0, actions: 0 });
  const [recent, setRecent] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get('/api/campaigns').catch(() => []),
      api.get('/api/accounts').catch(() => []),
      api.get('/api/decisions?limit=5').catch(() => []),
      api.get('/api/actions?limit=10').catch(() => []),
    ]).then(([campaigns, accounts, decisions, actions]) => {
      setCampaigns(Array.isArray(campaigns) ? campaigns : []);
      setStats({
        campaigns: Array.isArray(campaigns) ? campaigns.length : 0,
        accounts: Array.isArray(accounts) ? accounts.length : 0,
        decisions: Array.isArray(decisions) ? decisions.length : 0,
        actions: Array.isArray(actions) ? actions.length : 0,
      });
      setRecent(Array.isArray(decisions) ? decisions.slice(0, 5) : []);
    }).finally(() => setLoading(false));
  }, []);

  // Campaign stats summary
  const totalCost = campaigns.reduce((s, c) => s + (c.latest_cost || 0), 0);
  const activeCampaigns = campaigns.filter(c => c.status === 'active').length;

  const decisionStatusBadge = (status) => {
    const map = { pending: 'badge-warning', approved: 'badge-success', rejected: 'badge-error', executed: 'badge-info', completed: 'badge-success', failed: 'badge-error' };
    return <span className={`badge ${map[status] || 'badge-info'}`}>{status}</span>;
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Кампании', value: stats.campaigns, sub: `${activeCampaigns} активных` },
          { label: 'Аккаунты', value: stats.accounts },
          { label: 'Решения ИИ', value: stats.decisions },
          { label: 'Расход', value: `${totalCost.toFixed(2)} ₽`, sub: 'за всё время' },
        ].map((s, i) => (
          <div key={i} className="stat-card">
            <div className="text-sm text-muted-foreground">{s.label}</div>
            <div className="text-3xl font-bold mt-1" style={{ color: 'var(--neon)' }}>
              {loading ? '...' : s.value}
            </div>
            {s.sub && <div className="text-xs text-muted-foreground mt-1">{s.sub}</div>}
          </div>
        ))}
      </div>

      {/* Campaigns with sparklines */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">Кампании — обзор</h2>
        {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : (
          <table className="dark-table">
            <thead>
              <tr><th>Название</th><th>Статус</th><th>CTR</th><th>Расход</th><th>CTR 7д</th></tr>
            </thead>
            <tbody>
              {campaigns.slice(0, 10).map(c => (
                <tr key={c.id}>
                  <td className="font-medium">{c.name}</td>
                  <td>{statusBadge(c.status)}</td>
                  <td>{c.latest_ctr != null ? `${c.latest_ctr.toFixed(2)}%` : '—'}</td>
                  <td>{c.latest_cost != null ? `${c.latest_cost.toFixed(2)} ₽` : '—'}</td>
                  <td><Sparkline data={c.ctr_history || []} color="var(--neon)" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-4">Последние решения ИИ</h2>
        {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : recent.length === 0 ? (
          <p className="text-muted-foreground text-sm text-center py-4">Решений пока нет</p>
        ) : (
          <table className="dark-table">
            <thead><tr><th>Кампания</th><th>Статус</th><th>Дата</th></tr></thead>
            <tbody>
              {recent.map(d => (
                <tr key={d.id} style={{ animationDelay: '0.05s' }}>
                  <td className="font-medium">{d.campaign_id}</td>
                  <td>{decisionStatusBadge(d.status)}</td>
                  <td className="text-muted-foreground">{new Date(d.created_at).toLocaleString('ru-RU')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function AccountsPage() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ platform: 'wildberries', name: '', wb_token: '', ozon_client_id: '', ozon_client_secret: '' });
  const [editId, setEditId] = useState(null);
  const [error, setError] = useState('');

  const load = () => api.get('/api/accounts').then(setAccounts).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      if (editId) {
        await api.patch(`/api/accounts/${editId}`, form);
      } else {
        await api.post('/api/accounts', form);
      }
      setForm({ platform: 'wildberries', name: '', wb_token: '', ozon_client_id: '', ozon_client_secret: '' });
      setShowForm(false); setEditId(null);
      load();
    } catch (err) { setError(err.message); }
  };

  const handleSync = async (id) => {
    try {
      const result = await api.post(`/api/accounts/${id}/sync-campaigns`);
      alert(`Импортировано: ${result.imported || 0} из ${result.total || 0}`);
    } catch (err) { alert('Ошибка: ' + err.message); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Аккаунты</h2>
        <button className="btn btn-primary btn-sm" onClick={() => { setShowForm(!showForm); setEditId(null); setError(''); }}>
          {showForm ? 'Закрыть' : '+ Добавить'}
        </button>
      </div>

      {showForm && (
        <div className="card">
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Платформа</label>
                <select className="input" value={form.platform} onChange={e => setForm({...form, platform: e.target.value})}>
                  <option value="wildberries">Wildberries</option>
                  <option value="ozon">Ozon</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Название</label>
                <input className="input" value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="Мой магазин" required />
              </div>
            </div>
            {form.platform === 'wildberries' ? (
              <input className="input" placeholder="WB API Token" value={form.wb_token} onChange={e => setForm({...form, wb_token: e.target.value})} />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <input className="input" placeholder="Ozon Client ID" value={form.ozon_client_id} onChange={e => setForm({...form, ozon_client_id: e.target.value})} />
                <input className="input" placeholder="Ozon Client Secret" value={form.ozon_client_secret} onChange={e => setForm({...form, ozon_client_secret: e.target.value})} />
              </div>
            )}
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <button className="btn btn-primary btn-sm" type="submit">{editId ? 'Сохранить' : 'Создать'}</button>
          </form>
        </div>
      )}

      {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : (
        <table className="dark-table">
          <thead>
            <tr><th>Название</th><th>Платформа</th><th>Статус</th><th>Создан</th><th></th></tr>
          </thead>
          <tbody>
            {accounts.map(a => (
              <tr key={a.id}>
                <td className="font-medium">{a.name}</td>
                <td>{platformBadge(a.platform)}</td>
                <td><span className={`badge ${a.is_active ? 'badge-success' : 'badge-error'}`}>{a.is_active ? 'Активен' : 'Неактивен'}</span></td>
                <td className="text-muted-foreground">{new Date(a.created_at).toLocaleDateString('ru-RU')}</td>
                <td>
                  {a.platform === 'wildberries' && (
                    <button className="btn btn-secondary btn-sm" onClick={() => handleSync(a.id)}>Синхронизировать</button>
                  )}
                </td>
              </tr>
            ))}
            {accounts.length === 0 && (
              <tr><td colSpan="5" className="text-center text-muted-foreground py-8">Аккаунтов нет</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CampaignsPage() {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  const load = () => api.get('/api/campaigns').then(setCampaigns).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const filtered = campaigns.filter(c => c.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Кампании</h2>
        <span className="text-muted-foreground text-sm">{campaigns.length} кампаний</span>
      </div>
      <input className="input" placeholder="Поиск кампаний..." value={filter} onChange={e => setFilter(e.target.value)} />
      {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : (
        <table className="dark-table">
          <thead><tr><th>Название</th><th>Платформа</th><th>Статус</th><th>CTR</th><th>Расход</th><th>CTR 7д</th></tr></thead>
          <tbody>
            {filtered.map(c => (
              <tr key={c.id} onClick={() => window.location.hash = `#/campaigns/${c.id}`} className="cursor-pointer hover:bg-accent/50 transition-colors">
                <td className="font-medium">{c.name}</td>
                <td>{platformBadge(c.platform)}</td>
                <td>{statusBadge(c.status)}</td>
                <td>{c.latest_ctr != null ? `${c.latest_ctr.toFixed(2)}%` : '—'}</td>
                <td>{c.latest_cost != null ? `${c.latest_cost.toFixed(2)} ₽` : '—'}</td>
                <td><Sparkline data={c.ctr_history || []} /></td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan="6" className="text-center text-muted-foreground py-8">Кампаний нет</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CampaignDetailPage({ campaignId }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [decLoading, setDecLoading] = useState(true);
  const [kwEditingId, setKwEditingId] = useState(null);
  const [kwForm, setKwForm] = useState({});
  const [kwLoading, setKwLoading] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [showDatePicker, setShowDatePicker] = useState(false);

  const todayStr = () => new Date().toISOString().slice(0, 10);
  const daysAgoStr = (n) => {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  };

  const initDates = (from, to) => {
    if (from) {
      setDateFrom(from);
      setDateTo(to || todayStr());
    } else {
      setDateFrom(daysAgoStr(7));
      setDateTo(todayStr());
    }
  };

  const loadCampaign = (useFrom, useTo) => {
    setLoading(true); setError(null);
    const params = new URLSearchParams();
    const df = useFrom || dateFrom || daysAgoStr(7);
    const dt = useTo || dateTo || todayStr();
    if (df) params.set('date_from', df);
    if (dt) params.set('date_to', dt);
    api.get(`/api/campaigns/${campaignId}?${params}`)
      .then(d => {
        setDetail(d);
        initDates(d.date_from, d.date_to);
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));

    setDecLoading(true);
    api.get(`/api/decisions?campaign_id=${campaignId}&limit=20`)
      .then(d => setDecisions(Array.isArray(d) ? d : []))
      .catch(() => setDecisions([]))
      .finally(() => setDecLoading(false));
  };

  useEffect(() => {
    initDates();
    loadCampaign();
  }, [campaignId]);

  const applyDateRange = () => {
    setShowDatePicker(false);
    if (dateFrom && dateTo) {
      loadCampaign(dateFrom, dateTo);
    }
  };

  const setPreset = (days) => {
    setDateFrom(daysAgoStr(days));
    setDateTo(todayStr());
    loadCampaign(daysAgoStr(days), todayStr());
    setShowDatePicker(false);
  };

  const changeStatus = async (status) => {
    try {
      const updated = await api.post(`/api/campaigns/${campaignId}/status/${status}`);
      setDetail(d => d ? { ...d, status: updated.status } : d);
    } catch (e) { alert('Ошибка: ' + e.message); }
  };

  const editKeyword = async () => {
    setKwLoading(true);
    try {
      await api.patch(`/api/keywords/${kwEditingId}`, kwForm);
      setKwEditingId(null);
      setDetail(d => d ? {
        ...d,
        keywords: d.keywords.map(k => k.id === kwEditingId ? { ...k, ...kwForm } : k),
      } : d);
      setKwForm({});
    } catch (e) { alert('Ошибка: ' + e.message); }
    finally { setKwLoading(false); }
  };

  const deleteKeyword = async (id) => {
    if (!confirm('Удалить ключевое слово?')) return;
    try {
      await api.delete(`/api/keywords/${id}`);
      setDetail(d => d ? { ...d, keywords: d.keywords.filter(k => k.id !== id) } : d);
    } catch (e) { alert('Ошибка: ' + e.message); }
  };

  const toggleMinusWord = async (kw) => {
    const newStatus = kw.status === 'minus' ? 'active' : 'minus';
    try {
      await api.patch(`/api/keywords/${kw.id}`, { status: newStatus });
      setDetail(d => d ? {
        ...d,
        keywords: d.keywords.map(k => k.id === kw.id ? { ...k, status: newStatus } : k),
      } : d);
    } catch (e) { alert('Ошибка: ' + e.message); }
  };

  const actionTypeLabel = (t) => ({
    raise_bid: 'Повысить ставку', lower_bid: 'Снизить ставку', minus_word: 'Минус-слово',
    increase_budget: 'Увеличить бюджет', create_search_campaign: 'Создать кампанию', adjust_price: 'Скорректировать цену',
  }[t] || t);

  if (loading) return <div className="flex justify-center py-20"><div className="spinner" /></div>;
  if (error) return <div className="card text-center text-red-500 py-8">{error}</div>;
  if (!detail) return <div className="card text-center text-muted-foreground py-8">Кампания не найдена</div>;

  const d = detail;

  const totalImp = d.keywords?.reduce((s, kw) => s + (kw.total_impressions || 0), 0) || 0;
  const totalClk = d.keywords?.reduce((s, kw) => s + (kw.total_clicks || 0), 0) || 0;
  const totalCst = d.keywords?.reduce((s, kw) => s + (kw.total_cost || 0), 0) || 0;

  return (
    <div className="space-y-6">
      {/* Back button + header */}
      <button className="btn btn-secondary btn-sm" onClick={() => window.location.hash = '#/campaigns'}>
        ← Назад к кампаниям
      </button>

      <div className="card">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-xl font-bold">{d.name}</h2>
            <div className="text-xs text-muted-foreground mt-1">
              ID: {d.platform_campaign_id} &midddot; {platformBadge(d.platform)} {statusBadge(d.status)}
            </div>
          </div>
          <div className="flex gap-2 flex-wrap items-center">
            {/* Date selector */}
            <button className="btn btn-secondary btn-sm text-xs" onClick={() => setShowDatePicker(!showDatePicker)}>
              📅 {dateFrom} — {dateTo}
            </button>
            {d.status !== 'active' && (
              <button className="btn btn-primary btn-sm" onClick={() => changeStatus('active')}>Старт</button>
            )}
            {d.status !== 'paused' && (
              <button className="btn btn-secondary btn-sm" onClick={() => changeStatus('paused')}>Пауза</button>
            )}
            {d.status !== 'completed' && (
              <button className="btn btn-secondary btn-sm" onClick={() => changeStatus('completed')}>Стоп</button>
            )}
          </div>
        </div>

        {/* Date picker panel */}
        {showDatePicker && (
          <div className="bg-background/80 border border-border rounded-lg p-3 mb-4">
            <div className="text-xs text-muted-foreground mb-2 font-medium">Период:</div>
            {/* Preset buttons */}
            <div className="flex gap-2 mb-3 flex-wrap">
              <button className="btn btn-primary btn-sm text-xs" onClick={() => setPreset(1)}>1 день</button>
              <button className="btn btn-secondary btn-sm text-xs" onClick={() => setPreset(7)}>7 дней</button>
              <button className="btn btn-secondary btn-sm text-xs" onClick={() => setPreset(14)}>14 дней</button>
              <button className="btn btn-secondary btn-sm text-xs" onClick={() => setPreset(30)}>30 дней</button>
            </div>
            <div className="flex gap-3 items-center">
              <label className="text-xs flex items-center gap-1">
                С:
                <input type="date" className="input text-xs py-1" value={dateFrom}
                  onChange={e => setDateFrom(e.target.value)} />
              </label>
              <label className="text-xs flex items-center gap-1">
                По:
                <input type="date" className="input text-xs py-1" value={dateTo}
                  onChange={e => setDateTo(e.target.value)} />
              </label>
              <button className="btn btn-primary btn-sm text-xs" onClick={applyDateRange}>Применить</button>
            </div>
          </div>
        )}

        {/* Summary for selected period */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
          <div><div className="text-xs text-muted-foreground">Период</div><div className="font-medium">{dateFrom} — {dateTo}</div></div>
          <div><div className="text-xs text-muted-foreground">Показы</div><div className="font-medium">{totalImp}</div></div>
          <div><div className="text-xs text-muted-foreground">Клики</div><div className="font-medium">{totalClk}</div></div>
          <div><div className="text-xs text-muted-foreground">CTR</div><div className="font-medium" style={{ color: totalImp > 0 ? 'var(--neon)' : 'inherit' }}>{totalImp > 0 ? `${(totalClk / totalImp * 100).toFixed(2)}%` : '—'}</div></div>
          <div><div className="text-xs text-muted-foreground">Стоимость</div><div className="font-medium">{totalCst.toFixed(2)} ₽</div></div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div><div className="text-xs text-muted-foreground">Тип</div><div className="font-medium">{d.campaign_type ?? '—'}</div></div>
          <div><div className="text-xs text-muted-foreground">Бюджет/день</div><div className="font-medium">{d.daily_budget != null ? `${d.daily_budget} ₽` : '—'}</div></div>
          <div><div className="text-xs text-muted-foreground">Ставка</div><div className="font-medium">{d.current_bid != null ? `${d.current_bid} ₽` : '—'}</div></div>
          <div><div className="text-xs text-muted-foreground">CTR (последний)</div><div className="font-medium" style={{ color: d.latest_ctr != null ? 'var(--neon)' : 'inherit' }}>{d.latest_ctr != null ? `${d.latest_ctr.toFixed(2)}%` : '—'}</div></div>
        </div>

        <div className="mt-3">
          <div className="text-xs text-muted-foreground mb-1">CTR за последние 7 дней</div>
          <Sparkline data={d.ctr_history || []} color="var(--neon)" />
        </div>
      </div>

      {/* Keywords */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4">Ключевые слова ({d.keywords?.length || 0})</h3>
        {kwLoading && <div className="flex justify-center py-4"><div className="spinner" /></div>}
        {d.keywords?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="dark-table">
              <thead>
                <tr><th>Текст</th><th>Показы</th><th>Клики</th><th>CTR</th><th>Стоимость</th><th>Ставка</th><th>Статус</th><th>Действия</th></tr>
              </thead>
              <tbody>
                {d.keywords.map(kw => (
                  <tr key={kw.id}>
                    <td className="font-medium max-w-[250px] truncate" title={kw.keyword_text}>{kw.keyword_text ?? '—'}</td>
                    <td className="text-xs">{kw.total_impressions ?? 0}</td>
                    <td className="text-xs">{kw.total_clicks ?? 0}</td>
                    <td className="text-xs" style={{ color: kw.total_ctr != null ? 'var(--neon-green)' : 'inherit' }}>{kw.total_ctr != null ? `${kw.total_ctr.toFixed(2)}%` : '—'}</td>
                    <td className="text-xs">{kw.total_cost != null ? `${kw.total_cost.toFixed(2)} ₽` : '—'}</td>
                    {kwEditingId === kw.id ? (
                      <>
                        <td colSpan="5">
                          <div className="flex gap-2 items-center">
                            <select className="input text-xs py-1" value={kwForm.status ?? kw.status} onChange={e => setKwForm({...kwForm, status: e.target.value})}>
                              <option value="active">active</option>
                              <option value="minus">minus</option>
                              <option value="draft">draft</option>
                              <option value="unmanaged">unmanaged</option>
                            </select>
                            <input className="input text-xs py-1 w-20" type="number" step="0.01" placeholder="Ставка"
                              value={kwForm.current_bid ?? kw.current_bid ?? ''} onChange={e => setKwForm({...kwForm, current_bid: parseFloat(e.target.value) || null})} />
                            <button className="btn btn-primary btn-sm text-xs py-1" onClick={editKeyword} disabled={kwLoading}>OK</button>
                            <button className="btn btn-secondary btn-sm text-xs py-1" onClick={() => { setKwEditingId(null); setKwForm({}); }}>✕</button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>{kw.current_bid != null ? `${kw.current_bid} ₽` : '—'}</td>
                        <td><Badge variant={kw.status === 'active' ? 'success' : kw.status === 'minus' ? 'error' : 'info'}>{kw.status}</Badge></td>
                        <td>
                          <div className="flex gap-1 flex-wrap">
                            <button className="btn btn-secondary btn-sm text-xs py-0.5 px-1.5" onClick={() => { setKwEditingId(kw.id); setKwForm({}); }}>{kwLoading ? '...' : '✏️'}</button>
                            <button className="btn btn-secondary btn-sm text-xs py-0.5 px-1.5" onClick={() => toggleMinusWord(kw)}>{kw.status === 'minus' ? 'Разминусовать' : 'Минус'}</button>
                            <button className="btn btn-secondary btn-sm text-xs py-0.5 px-1.5" onClick={() => deleteKeyword(kw.id)}>🗑</button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm text-center py-4">Ключевых слов нет</p>
        )}
      </div>

      {/* LLM Decisions */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4">Решения ИИ ({decisions.length})</h3>
        {decLoading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : decisions.length > 0 ? (
          <div className="space-y-3">
            {decisions.map(dec => {
              const actions = dec.actions_json?.actions || [];
              return (
                <div key={dec.id} className="p-3 rounded bg-muted/30">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={{ pending: 'warning', approved: 'success', rejected: 'error', executed: 'info', completed: 'success', failed: 'error' }[dec.status] || 'info'}>
                        {dec.status}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{new Date(dec.created_at).toLocaleString('ru-RU')}</span>
                    </div>
                  </div>
                  {dec.prompt_text && (
                    <details className="text-xs mb-2">
                      <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors">Показать промпт</summary>
                      <pre className="bg-background/50 p-2 rounded mt-1 text-xs whitespace-pre-wrap max-h-40 overflow-y-auto">{dec.prompt_text}</pre>
                    </details>
                  )}
                  {actions.length > 0 && (
                    <div className="space-y-1">
                      {actions.map((act, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs p-1.5 rounded bg-background/50">
                          <Badge variant="info">{actionTypeLabel(act.action_type)}</Badge>
                          <span className="text-muted-foreground">{act.status ?? ''}</span>
                          {act.metrics_before_json && (
                            <details>
                              <summary className="cursor-pointer text-muted-foreground">метрики</summary>
                              <pre className="text-xs mt-1 bg-background p-1 rounded overflow-auto max-h-32">{JSON.stringify(act.metrics_before_json, null, 2)}</pre>
                            </details>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm text-center py-4">Решений ИИ пока нет</p>
        )}
      </div>
    </div>
  );
}

function DecisionsPage() {
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(null);

  const load = () => api.get('/api/decisions?limit=50').then(setDecisions).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const handleAction = async (id, action) => {
    setProcessing(id);
    try {
      await api.post(`/api/decisions/${id}/${action}`);
      load();
    } catch (e) { alert(e.message); }
    setProcessing(null);
  };

  const statusBadgeVal = (s) => {
    const map = { pending: 'badge-warning', approved: 'badge-success', rejected: 'badge-error', executed: 'badge-info' };
    return <span className={`badge ${map[s] || 'badge-info'}`}>{s}</span>;
  };

  const actionTypeLabel = (t) => ({
    raise_bid: 'Повысить ставку', lower_bid: 'Снизить ставку', minus_word: 'Минус-слово',
    increase_budget: 'Увеличить бюджет', create_search_campaign: 'Создать кампанию', adjust_price: 'Скорректировать цену',
  }[t] || t);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">Решения ИИ</h2>
      {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : (
        <div className="space-y-4">
          {decisions.map(d => {
            const actions = d.actions_json?.actions || [];
            return (
              <div key={d.id} className="card">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-muted-foreground">Кампания: {d.campaign_id}</span>
                    {statusBadgeVal(d.status)}
                  </div>
                  <span className="text-xs text-muted-foreground">{new Date(d.created_at).toLocaleString('ru-RU')}</span>
                </div>
                {actions.length > 0 && (
                  <div className="space-y-2 mb-3">
                    {actions.map((action, i) => (
                      <div key={i} className="flex items-center gap-2 text-sm p-2 rounded bg-muted/30">
                        <span className="badge badge-info">{actionTypeLabel(action.action_type)}</span>
                        {action.status && <span className="text-muted-foreground text-xs">{action.status}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {d.status === 'pending' && (
                  <div className="flex gap-2 pt-2">
                    <button className="btn btn-primary btn-sm" disabled={!!processing} onClick={() => handleAction(d.id, 'approve')}>
                      {processing === d.id ? '...' : 'Принять'}
                    </button>
                    <button className="btn btn-secondary btn-sm" disabled={!!processing} onClick={() => handleAction(d.id, 'reject')}>
                      Отклонить
                    </button>
                  </div>
                )}
              </div>
            );
          })}
          {decisions.length === 0 && (
            <div className="card text-center text-muted-foreground py-8">Решений ИИ пока нет</div>
          )}
        </div>
      )}
    </div>
  );
}

function ActionsPage() {
  const [actions, setActions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewAction, setViewAction] = useState(null);

  const load = () => api.get('/api/actions?limit=50').then(setActions).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const typeLabel = (t) => ({
    raise_bid: 'Повысить ставку', lower_bid: 'Снизить ставку', minus_word: 'Минус-слово',
    increase_budget: 'Увеличить бюджет', create_search_campaign: 'Создать кампанию', adjust_price: 'Скорректировать цену',
  }[t] || t);

  const statusBadgeVal = (s) => {
    const map = { executed: 'badge-success', failed: 'badge-error', pending: 'badge-warning', approved: 'badge-info' };
    return <span className={`badge ${map[s] || 'badge-info'}`}>{s}</span>;
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">Журнал действий</h2>
      {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : (
        <table className="dark-table">
          <thead><tr><th>Тип</th><th>Статус</th><th>Кампания</th><th>Дата</th><th></th></tr></thead>
          <tbody>
            {actions.map(a => (
              <tr key={a.id}>
                <td>{typeLabel(a.action_type)}</td>
                <td>{statusBadgeVal(a.status)}</td>
                <td className="text-muted-foreground">{a.campaign_id ?? '—'}</td>
                <td className="text-muted-foreground">{a.applied_at ? new Date(a.applied_at).toLocaleString('ru-RU') : '—'}</td>
                <td>
                  <button className="btn btn-secondary btn-sm text-xs py-0.5 px-2" onClick={() => setViewAction(a)}>Детали</button>
                </td>
              </tr>
            ))}
            {actions.length === 0 && (
              <tr><td colSpan="5" className="text-center text-muted-foreground py-8">Действий не было</td></tr>
            )}
          </tbody>
        </table>
      )}

      {/* Action detail modal */}
      {viewAction && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setViewAction(null)}>
          <div className="card max-w-lg w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">{typeLabel(viewAction.action_type)}</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setViewAction(null)}>Закрыть</button>
            </div>
            <div className="space-y-3 text-sm">
              <div><span className="text-muted-foreground">Статус:</span> {statusBadgeVal(viewAction.status)}</div>
              <div><span className="text-muted-foreground">Кампания:</span> {viewAction.campaign_id ?? '—'}</div>
              <div><span className="text-muted-foreground">Применено:</span> {viewAction.applied_at ? new Date(viewAction.applied_at).toLocaleString('ru-RU') : '—'}</div>

              <details>
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Параметры действия</summary>
                <pre className="bg-background/50 p-2 rounded text-xs mt-1 whitespace-pre-wrap max-h-40 overflow-y-auto">{JSON.stringify(viewAction.parameters_json, null, 2)}</pre>
              </details>

              <details>
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Метрики до</summary>
                <pre className="bg-background/50 p-2 rounded text-xs mt-1 whitespace-pre-wrap max-h-40 overflow-y-auto">{JSON.stringify(viewAction.metrics_before_json, null, 2)}</pre>
              </details>

              {viewAction.metrics_after_json && (
                <details>
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Метрики после</summary>
                  <pre className="bg-background/50 p-2 rounded text-xs mt-1 whitespace-pre-wrap max-h-40 overflow-y-auto">{JSON.stringify(viewAction.metrics_after_json, null, 2)}</pre>
                </details>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Rules Page ──

function RulesPage() {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ platform: 'wildberries', rule_name: '', rule_description: '', rule_params_json: {} });
  const [editId, setEditId] = useState(null);

  const load = () => api.get('/api/rules').then(setRules).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      let params = {};
      try { params = typeof form.rule_params_json === 'string' ? JSON.parse(form.rule_params_json) : form.rule_params_json; } catch {}
      const data = { ...form, rule_params_json: params };
      if (editId) {
        await api.patch(`/api/rules/${editId}`, data);
      } else {
        await api.post('/api/rules', data);
      }
      load();
    } catch (e) { alert(e.message); }
    setShowForm(false);
    setEditId(null);
    setForm({ platform: 'wildberries', rule_name: '', rule_description: '', rule_params_json: {} });
  };

  const editRule = (rule) => {
    setEditId(rule.id);
    setForm({ platform: rule.platform, rule_name: rule.rule_name, rule_description: rule.rule_description || '', rule_params_json: typeof rule.rule_params_json === 'object' ? JSON.stringify(rule.rule_params_json, null, 2) : rule.rule_params_json });
    setShowForm(true);
  };

  const toggleRule = async (rule) => {
    try {
      await api.patch(`/api/rules/${rule.id}`, { is_active: !rule.is_active });
      load();
    } catch (e) { alert(e.message); }
  };

  const deleteRule = async (id) => {
    if (!confirm('Удалить правило?')) return;
    try { await api.delete(`/api/rules/${id}`); load(); }
    catch (e) { alert(e.message); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Правила оптимизации</h2>
        <button className="btn btn-primary btn-sm" onClick={() => { setShowForm(!showForm); setEditId(null); }}>
          {showForm ? 'Закрыть' : '+ Добавить'}
        </button>
      </div>

      {showForm && (
        <div className="card">
          <form onSubmit={handleSubmit} className="space-y-3">
            <input className="input" placeholder="Название" value={form.rule_name} onChange={e => setForm({...form, rule_name: e.target.value})} required />
            <textarea className="input" placeholder="Описание" value={form.rule_description} onChange={e => setForm({...form, rule_description: e.target.value})} rows="2" />
            <select className="input" value={form.platform} onChange={e => setForm({...form, platform: e.target.value})}>
              <option value="wildberries">Wildberries</option>
              <option value="ozon">Ozon</option>
              <option value="all">Все платформы</option>
            </select>
            <textarea className="input font-mono text-xs" placeholder='{"threshold": 10, "adjustment_pct": 15}'
              value={form.rule_params_json} onChange={e => setForm({...form, rule_params_json: e.target.value})} rows="4" />
            <button className="btn btn-primary btn-sm" type="submit">{editId ? 'Сохранить' : 'Создать'}</button>
          </form>
        </div>
      )}

      {loading ? <div className="flex justify-center py-8"><div className="spinner" /></div> : (
        <table className="dark-table">
          <thead><tr><th>Название</th><th>Платформа</th><th>Описание</th><th>Параметры</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {rules.map(r => (
              <tr key={r.id}>
                <td className="font-medium">{r.rule_name}</td>
                <td>{platformBadge(r.platform)}</td>
                <td className="text-muted-foreground text-sm max-w-[200px] truncate">{r.rule_description ?? '—'}</td>
                <td><pre className="text-xs max-h-20 overflow-y-auto">{JSON.stringify(r.rule_params_json, null, 2)}</pre></td>
                <td>
                  <button className={`badge cursor-pointer ${r.is_active ? 'badge-success' : 'badge-error'}`} onClick={() => toggleRule(r)}>
                    {r.is_active ? 'Активно' : 'Неактивно'}
                  </button>
                </td>
                <td>
                  <div className="flex gap-1">
                    <button className="btn btn-secondary btn-sm text-xs py-0.5 px-1.5" onClick={() => editRule(r)}>✏️</button>
                    <button className="btn btn-secondary btn-sm text-xs py-0.5 px-1.5" onClick={() => deleteRule(r.id)}>✕</button>
                  </div>
                </td>
              </tr>
            ))}
            {rules.length === 0 && (
              <tr><td colSpan="6" className="text-center text-muted-foreground py-8">Правил нет</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SettingsPage() {
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({llm_provider:'', llm_model:'', base_url:'', auto_mode: false, analysis_interval_hours: 1, max_campaigns_per_run: 10});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get('/api/analysis/settings').then(d => {
      setSettings(d || {});
      setForm({
        llm_provider: d?.llm_provider || '',
        llm_model: d?.llm_model || '',
        base_url: d?.base_url || '',
        auto_mode: d?.auto_mode ?? false,
        analysis_interval_hours: d?.analysis_interval_hours ?? 1,
        max_campaigns_per_run: d?.max_campaigns_per_run ?? 10,
      });
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true); setSaved(false);
    try { await api.post('/api/analysis/settings', form); setSaved(true); setTimeout(() => setSaved(false), 2000); }
    catch (e) { alert('Ошибка: ' + e.message); }
    setSaving(false);
  };

  if (loading) return <div className="flex justify-center py-20"><div className="spinner" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Настройки</h2>
        {saved && <span className="text-green-500 text-sm">Сохранено!</span>}
      </div>

      <div className="card space-y-4">
        <h3 className="text-lg font-semibold">Анализ ИИ</h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Провайдер LLM</label>
            <input className="input" value={form.llm_provider} onChange={e => setForm({...form, llm_provider: e.target.value})} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Модель</label>
            <input className="input" value={form.llm_model} onChange={e => setForm({...form, llm_model: e.target.value})} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Base URL</label>
            <input className="input" value={form.base_url} onChange={e => setForm({...form, base_url: e.target.value})} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Интервал анализа (часы)</label>
            <input className="input" type="number" min="1" value={form.analysis_interval_hours} onChange={e => setForm({...form, analysis_interval_hours: parseInt(e.target.value) || 1})} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Кол-во кампаний за запуск</label>
            <input className="input" type="number" min="1" value={form.max_campaigns_per_run} onChange={e => setForm({...form, max_campaigns_per_run: parseInt(e.target.value) || 10})} />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.auto_mode} onChange={e => setForm({...form, auto_mode: e.target.checked})} />
            <span className="text-sm">Автоматический режим</span>
          </label>
          <span className="text-xs text-muted-foreground">{form.auto_mode ? 'Решения применяются автоматически' : 'Требуют подтверждения'}</span>
        </div>

        <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
          {saving ? 'Сохранение...' : 'Сохранить'}
        </button>
      </div>
    </div>
  );
}

// ── Router ──

export default function App() {
  const [hash, setHash] = useState(window.location.hash || '#/');

  useEffect(() => {
    const handler = () => setHash(window.location.hash || '#/');
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  const parsedHash = () => {
    const h = hash || '#/';
    const m = h.match(/^#\/campaigns\/(\d+)$/);
    if (m) return { page: 'campaignDetail', id: parseInt(m[1]) };
    return { page: h === '#/' || h === '' ? 'dashboard' : h.replace('#/', '') };
  };

  const p = parsedHash();

  const route = () => {
    if (p.page === 'dashboard') return <DashboardPage />;
    if (p.page === 'accounts') return <AccountsPage />;
    if (p.page === 'campaigns') return <CampaignsPage />;
    if (p.page === 'campaignDetail') return <CampaignDetailPage campaignId={p.id} />;
    if (p.page === 'decisions') return <DecisionsPage />;
    if (p.page === 'actions') return <ActionsPage />;
    if (p.page === 'rules') return <RulesPage />;
    if (p.page === 'settings') return <SettingsPage />;
    return <DashboardPage />;
  };

  const titles = {
    'dashboard': 'Dashboard', 'accounts': 'Аккаунты', 'campaigns': 'Кампании',
    'decisions': 'Решения ИИ', 'actions': 'Действия', 'rules': 'Правила',
    'settings': 'Настройки', 'campaignDetail': 'Детали кампании',
  };

  return <Layout title={titles[p.page] || 'AI Ads Manager'} page={p.page} hash={hash}>{route()}</Layout>;
}
