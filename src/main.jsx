import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  CloudDownload,
  GraduationCap,
  Home,
  LoaderCircle,
  LogOut,
  Menu,
  Network,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import "./styles.css";

const navItems = [
  ["overview", "首页", Home],
  ["grades", "成绩", GraduationCap],
  ["schedule", "课表", CalendarDays],
  ["network", "网络设备", Network],
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
    throw new Error(isLocal
      ? `本地 API 未返回 JSON（HTTP ${response.status}）。请确认 npm run dev 的 API 进程仍在运行。`
      : `Vercel API 未正确响应（HTTP ${response.status}）。请检查本次部署的 Functions 和运行日志。`);
  }
  const payload = await response.json();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail : payload;
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return payload;
}

function Spinner({ label = "正在加载" }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={20} />
      <span>{label}</span>
    </div>
  );
}

function ErrorNotice({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="error-notice" role="alert">
      <CircleAlert size={19} />
      <span>{error}</span>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>重试</button>
      )}
    </div>
  );
}

function LoginPage({ onLoggedIn }) {
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [ticket, setTicket] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submitLogin(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          account,
          password,
          remember,
          device_id: "ZZU.Py Web",
        }),
      });
      if (result.mfa_required) {
        setTicket(result.ticket);
        setPassword("");
      } else {
        onLoggedIn(result.account);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitMfa(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api("/api/auth/mfa", {
        method: "POST",
        body: JSON.stringify({ ticket, code }),
      });
      onLoggedIn(result.account);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-story">
        <div className="brand-mark"><Sparkles size={22} /> ZZU LIFE</div>
        <div className="story-copy">
          <p className="eyebrow">郑州大学 · 数字生活</p>
          <h1>校园信息，<br /><em>清晰一点。</em></h1>
          <p className="story-lead">
            一处查看课程成绩与每周课表。少一点跳转，
            多一点从容。
          </p>
        </div>
        <div className="story-metrics" aria-label="功能摘要">
          <div><strong>多学期</strong><span>课程成绩</span></div>
          <div><strong>7×10</strong><span>教学周课表</span></div>
          <div><strong>.ics</strong><span>日历导出</span></div>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="mobile-brand">ZZU LIFE</div>
          {ticket ? (
            <form onSubmit={submitMfa}>
              <div className="form-heading">
                <span className="icon-chip"><ShieldCheck size={22} /></span>
                <div><h2>短信验证</h2><p>验证码已发送到安全手机</p></div>
              </div>
              <label className="field-label" htmlFor="mfa-code">短信验证码</label>
              <input
                id="mfa-code"
                className="text-input code-input"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                required
              />
              <ErrorNotice error={error} />
              <button className="primary-button" disabled={busy}>
                {busy ? <LoaderCircle className="spin" /> : <>完成登录 <ArrowRight /></>}
              </button>
              <button type="button" className="subtle-button" onClick={() => setTicket("")}>
                返回账号登录
              </button>
            </form>
          ) : (
            <form onSubmit={submitLogin}>
              <div className="form-heading">
                <span className="icon-chip"><GraduationCap size={23} /></span>
                <div><h2>统一认证登录</h2><p>使用郑州大学统一身份认证</p></div>
              </div>
              <label className="field-label" htmlFor="account">学号</label>
              <input
                id="account"
                className="text-input"
                value={account}
                onChange={(event) => setAccount(event.target.value)}
                autoComplete="username"
                placeholder="请输入学号"
                required
              />
              <label className="field-label" htmlFor="password">密码</label>
              <input
                id="password"
                className="text-input"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                placeholder="请输入统一认证密码"
                required
              />
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(event) => setRemember(event.target.checked)}
                />
                <span>30 天内保持登录</span>
              </label>
              <ErrorNotice error={error} />
              <button className="primary-button" disabled={busy}>
                {busy ? <LoaderCircle className="spin" /> : <>登录 <ArrowRight /></>}
              </button>
              <p className="security-note">
                <ShieldCheck size={15} /> 密码仅存在加密的 HttpOnly 会话中，前端脚本无法读取。
              </p>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}

function PageHeader({ eyebrow, title, description, action }) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </header>
  );
}

function Overview({ account, navigate }) {
  const today = new Intl.DateTimeFormat("zh-CN", {
    month: "long", day: "numeric", weekday: "long",
  }).format(new Date());
  const cards = [
    ["grades", BookOpenCheck, "课程成绩", "按学期整理全部成绩", "#9bd8ff"],
    ["schedule", CalendarDays, "本周课表", "查看课次并导出日历", "#ffc799"],
  ];
  return (
    <div>
      <PageHeader
        eyebrow={today}
        title={`你好，${account}`}
        description="今天想先查看哪一项？"
      />
      <div className="hero-card">
        <div>
          <span className="hero-badge"><Sparkles size={15} /> 校园生活面板</span>
          <h2>需要的信息，<br />都在这里。</h2>
          <p>数据来自郑州大学相关服务，仅在你主动查询时获取。</p>
        </div>
        <div className="hero-orbit" aria-hidden="true">
          <span className="orbit-core"><GraduationCap /></span>
          <span className="orbit-dot dot-one" />
          <span className="orbit-dot dot-two" />
        </div>
      </div>
      <div className="quick-grid">
        {cards.map(([id, Icon, title, copy, color]) => (
          <button key={id} className="quick-card" onClick={() => navigate(id)}>
            <span className="quick-icon" style={{ background: color }}><Icon /></span>
            <span><strong>{title}</strong><small>{copy}</small></span>
            <ChevronRight className="quick-arrow" />
          </button>
        ))}
      </div>
      <div className="privacy-strip">
        <ShieldCheck />
        <div><strong>会话由服务端加密保护</strong><span>页面不会把密码写入浏览器存储。</span></div>
      </div>
    </div>
  );
}

function GradesView() {
  const [grades, setGrades] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/grades").then((result) => setGrades(result.grades)).catch((e) => setError(e.message));
  }, []);
  const grouped = useMemo(() => {
    const result = {};
    for (const grade of grades || []) (result[grade.semester || "未知学期"] ||= []).push(grade);
    return result;
  }, [grades]);
  return (
    <div>
      <PageHeader eyebrow="ACADEMIC RECORD" title="课程成绩" description="按学期查看已发布成绩与学分" />
      <ErrorNotice error={error} />
      {!grades && !error ? <Spinner label="正在读取成绩" /> : (
        <div className="semester-list">
          {Object.entries(grouped).sort(([a], [b]) => b.localeCompare(a)).map(([semester, items], index) => (
            <details className="semester-card" key={semester} open={index === 0}>
              <summary><span><CalendarDays size={18} />{semester}</span><em>{items.length} 门课程</em></summary>
              <div className="grade-table-wrap">
                <table className="data-table">
                  <thead><tr><th>课程</th><th>总评</th><th>成绩等级</th><th>平时</th><th>卷面</th><th>实验</th><th>绩点</th><th>学分</th><th>状态</th></tr></thead>
                  <tbody>{items.map((grade, itemIndex) => (
                    <tr key={`${grade.course}-${itemIndex}`} title={grade.detail || undefined}>
                      <td>{grade.course}</td><td className="score-cell">{grade.score || "未发布"}</td>
                      <td className="component-cell">{grade.level || "—"}</td>
                      <td className="component-cell">{grade.usual_score || "—"}</td>
                      <td className="component-cell">{grade.paper_score || "—"}</td>
                      <td className="component-cell">{grade.experiment_score || "—"}</td>
                      <td>{grade.gp ?? "—"}</td><td>{grade.credits}</td>
                      <td><span className={`status-pill ${grade.passed === false ? "fail" : grade.passed === true ? "pass" : "pending"}`}>{grade.passed === false ? "未通过" : grade.passed === true ? "通过" : "待定"}</span></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </details>
          ))}
        </div>
      )}
      <p className="page-footnote">当前接口没有班级或专业对比数据，因此不展示不可靠的排名。</p>
    </div>
  );
}

function ScheduleView() {
  const [semesters, setSemesters] = useState([]);
  const [semesterId, setSemesterId] = useState("");
  const [week, setWeek] = useState(1);
  const [lessons, setLessons] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/semesters").then((result) => {
      const sorted = [...result.semesters].sort((a, b) => b.start_date.localeCompare(a.start_date));
      setSemesters(sorted); if (sorted[0]) setSemesterId(String(sorted[0].id));
    }).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, []);
  const selected = semesters.find((item) => String(item.id) === semesterId);
  async function querySchedule() {
    if (!semesterId) return;
    setLoading(true); setError("");
    try {
      const result = await api(`/api/schedule?semester_id=${semesterId}&week=${week}`);
      setLessons(result.lessons);
    } catch (requestError) { setError(requestError.message); }
    finally { setLoading(false); }
  }
  async function downloadCalendar() {
    setError("");
    try {
      const response = await fetch(`/api/calendar?semester_id=${semesterId}`, { credentials: "include" });
      if (!response.ok) {
        const body = await response.json(); throw new Error(body.detail || "导出失败");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = `郑大课表_${selected?.school_year || semesterId}.ics`;
      link.click(); URL.revokeObjectURL(url);
    } catch (requestError) { setError(requestError.message); }
  }
  const weekdays = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  return (
    <div>
      <PageHeader eyebrow="WEEKLY SCHEDULE" title="我的课表" description="选择学期与教学周，查看本周全部课次" />
      <div className="schedule-toolbar">
        <label><span>学期</span><select value={semesterId} onChange={(e) => { setSemesterId(e.target.value); setWeek(1); }}>
          {semesters.map((item) => <option key={item.id} value={item.id}>{item.school_year} · {item.name}</option>)}
        </select></label>
        <label><span>教学周</span><input type="number" min="1" max={selected?.weeks || 30} value={week} onChange={(e) => setWeek(Number(e.target.value))} /></label>
        <button className="primary-button compact" onClick={querySchedule} disabled={loading || !semesterId}>查询课表</button>
        <button className="outline-button" onClick={downloadCalendar} disabled={!semesterId}><CloudDownload size={17} />下载 iCalendar</button>
      </div>
      <ErrorNotice error={error} />
      {loading ? <Spinner label="正在读取课表" /> : lessons === null ? (
        <div className="empty-state"><CalendarDays /><h3>选择教学周后查询</h3><p>也可以直接下载整个学期的 iCalendar 文件。</p></div>
      ) : lessons.length === 0 ? (
        <div className="empty-state"><CheckCircle2 /><h3>这一周没有课程</h3><p>可以切换其他教学周继续查看。</p></div>
      ) : (
        <div className="lesson-list">
          {lessons.map((lesson, index) => (
            <article className="lesson-card" key={`${lesson.date}-${lesson.start_unit}-${index}`}>
              <div className="lesson-date"><strong>{weekdays[lesson.weekday]}</strong><span>{lesson.date.slice(5)}</span></div>
              <div className="lesson-main"><h3>{lesson.course}</h3><p>{lesson.teacher || "教师未定"} · {lesson.place || "地点未定"}</p></div>
              <div className="lesson-units">第 {lesson.start_unit}–{lesson.end_unit} 节</div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function NetworkView() {
  return (
    <div>
      <PageHeader eyebrow="CAMPUS NETWORK" title="网络设备" description="校园网在线终端管理" />
      <div className="network-limit-card">
        <span className="network-graphic"><Network /></span>
        <div><span className="limit-label">仅限校园内网</span><h2>云端无法直连设备服务</h2>
          <p>设备自助服务位于郑大内网地址 <code>10.2.7.16</code>。Vercel 在公网运行，无法安全访问该地址，因此网页端不提供虚假的“下线”按钮。</p>
          <div className="desktop-tip"><ShieldCheck /><span><strong>请使用桌面版</strong>查看在线设备并在二次确认后下线。</span></div>
        </div>
      </div>
    </div>
  );
}

function AppShell({ account, onLogout }) {
  const displayAccount = typeof account === "string" && account ? account : "未登录";
  const [page, setPage] = useState("overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const views = {
    overview: <Overview account={account} navigate={setPage} />,
    grades: <GradesView />, schedule: <ScheduleView />,
    network: <NetworkView />,
  };
  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <div className="sidebar-brand"><span><Sparkles /></span><div><strong>ZZU LIFE</strong><small>郑大生活助手</small></div></div>
        <nav>{navItems.map(([id, label, Icon]) => (
          <button className={page === id ? "active" : ""} key={id} onClick={() => { setPage(id); setMenuOpen(false); }}><Icon />{label}</button>
        ))}</nav>
        <div className="sidebar-account"><span>{displayAccount.slice(-2)}</span><div><strong>{displayAccount}</strong><small>统一认证账号</small></div><button aria-label="退出登录" onClick={onLogout}><LogOut /></button></div>
      </aside>
      {menuOpen && <button className="menu-scrim" aria-label="关闭菜单" onClick={() => setMenuOpen(false)} />}
      <main className="content-area">
        <div className="mobile-bar"><button onClick={() => setMenuOpen(true)} aria-label="打开菜单"><Menu /></button><strong>ZZU LIFE</strong><button onClick={onLogout} aria-label="退出登录"><LogOut /></button></div>
        <div className="content-inner">{views[page]}</div>
      </main>
    </div>
  );
}

function App() {
  const [status, setStatus] = useState("loading");
  const [account, setAccount] = useState("");
  useEffect(() => {
    api("/api/session").then((result) => {
      if (typeof result.account !== "string" || !result.account) {
        throw new Error("登录会话缺少账号信息");
      }
      setAccount(result.account); setStatus("authenticated");
    }).catch(() => setStatus("guest"));
  }, []);
  async function logout() {
    try { await api("/api/auth/logout", { method: "POST", body: "{}" }); }
    finally { setAccount(""); setStatus("guest"); }
  }
  if (status === "loading") return <div className="app-loading"><Sparkles /><Spinner label="正在恢复会话" /></div>;
  if (status === "guest") return <LoginPage onLoggedIn={(value) => { setAccount(value); setStatus("authenticated"); }} />;
  return <AppShell account={account} onLogout={logout} />;
}

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <main className="fatal-error">
          <CircleAlert size={36} />
          <h1>页面暂时无法显示</h1>
          <p>{this.state.error.message || "发生未知错误"}</p>
          <button className="primary-button" onClick={() => window.location.reload()}>
            重新加载
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <AppErrorBoundary><App /></AppErrorBoundary>,
);
