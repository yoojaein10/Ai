import type { ReactNode } from "react";

type PageShellProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  toolbar?: ReactNode;
  contextPanel?: ReactNode;
  children: ReactNode;
};

export function PageShell({
  title,
  subtitle,
  actions,
  toolbar,
  contextPanel,
  children,
}: PageShellProps) {
  return (
    <div className="insa-page" style={{ containerType: "inline-size" }}>
      <header className="insa-page-header">
        <div className="insa-page-title-wrap">
          <h1 className="insa-page-title">{title}</h1>
          {subtitle && <p className="insa-page-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="insa-page-actions">{actions}</div>}
      </header>
      {toolbar && <div className="insa-page-toolbar">{toolbar}</div>}
      <div className={`insa-page-body${contextPanel ? " with-context" : ""}`}>
        <div className="insa-page-primary">{children}</div>
        {contextPanel && <aside className="insa-page-context">{contextPanel}</aside>}
      </div>
    </div>
  );
}
