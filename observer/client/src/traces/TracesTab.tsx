export function TracesTab() {
  const traces = [
    {
      id: "trace-7f31",
      name: "GET /api/users",
      duration: "245 ms",
      service: "observer-server",
      status: "ok",
    },
    {
      id: "trace-3cc9",
      name: "POST /api/users",
      duration: "312 ms",
      service: "observer-server",
      status: "warn",
    },
    {
      id: "trace-991a",
      name: "GET /api/traces",
      duration: "189 ms",
      service: "collector",
      status: "ok",
    },
  ];

  return (
    <section className="tab-panel" role="tabpanel">
      <div className="panel-toolbar">
        <div className="panel-toolbar__title">
          <span className="panel-toolbar__glyph" aria-hidden="true">
            T
          </span>
          <span>Recent traces</span>
        </div>
        <div className="panel-toolbar__meta">
          <span>{traces.length} samples</span>
          <span>Tail mode</span>
        </div>
      </div>

      <div className="trace-list">
        {traces.map((trace) => (
          <article key={trace.id} className="trace-card">
            <div className="trace-card__main">
              <div className="trace-card__header">
                <span className="trace-card__id">{trace.id}</span>
                <span className={`trace-status trace-status--${trace.status}`}>{trace.status}</span>
              </div>
              <p className="trace-card__name">{trace.name}</p>
              <p className="trace-card__service">{trace.service}</p>
            </div>
            <div className="trace-card__duration">{trace.duration}</div>
          </article>
        ))}
      </div>
    </section>
  );
}
