import { Caption1, Text, makeStyles, tokens } from "@fluentui/react-components";
import { useEffect, useRef, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { devIdentity } from "../api/client";

const useStyles = makeStyles({
  root: {
    minHeight: "100vh",
    display: "grid",
    gridTemplateRows: "auto 1fr",
    gridTemplateColumns: "220px 1fr",
    gridTemplateAreas: `"header header" "nav main"`,
    backgroundColor: tokens.colorNeutralBackground2,
    "@media (max-width: 720px)": {
      gridTemplateColumns: "1fr",
      gridTemplateAreas: `"header" "nav" "main"`,
    },
  },
  skip: {
    position: "absolute",
    left: "-10000px",
    ":focus": {
      left: tokens.spacingHorizontalM,
      top: tokens.spacingVerticalM,
      zIndex: 1,
      padding: tokens.spacingHorizontalS,
      backgroundColor: tokens.colorNeutralBackground1,
    },
  },
  header: {
    gridArea: "header",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.spacingHorizontalM,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalXL}`,
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  nav: {
    gridArea: "nav",
    padding: tokens.spacingVerticalM,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRight: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  navList: { listStyle: "none", margin: 0, padding: 0, display: "grid", gap: tokens.spacingVerticalXS },
  navLink: {
    display: "block",
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
    textDecoration: "none",
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
    ":focus-visible": { outline: `${tokens.strokeWidthThick} solid ${tokens.colorStrokeFocus2}` },
  },
  active: {
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground2,
    fontWeight: tokens.fontWeightSemibold,
  },
  main: { gridArea: "main", padding: tokens.spacingHorizontalXXL, minWidth: 0 },
});

/** The page a path belongs to: tabs within one project (`/projects/:id/:tab`) share a page. */
export function pageKey(pathname: string): string {
  return pathname.split("/").slice(0, 3).join("/");
}

/**
 * After navigating to a different page, move focus to the main region so keyboard and
 * screen-reader users land on the new page (and any closed modal releases focus).
 * Switching tabs within a page keeps focus on the tab list.
 */
function useFocusMainOnNavigation() {
  const page = pageKey(useLocation().pathname);
  const mainRef = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
  }, [page]);
  return mainRef;
}

export function AppShell({ children }: { children: ReactNode }) {
  const styles = useStyles();
  const mainRef = useFocusMainOnNavigation();
  return (
    <div className={styles.root}>
      <a className={styles.skip} href="#main">
        Skip to main content
      </a>
      <header className={styles.header}>
        <Text weight="semibold" size={400}>
          Enterprise AI Application Workspace
        </Text>
        <Caption1>
          {devIdentity.user} · tenant {devIdentity.tenant} (development sign-in)
        </Caption1>
      </header>
      <nav className={styles.nav} aria-label="Workspace">
        <ul className={styles.navList}>
          <li>
            <NavLink
              to="/projects"
              className={({ isActive }) => (isActive ? `${styles.navLink} ${styles.active}` : styles.navLink)}
            >
              Projects
            </NavLink>
          </li>
          <li>
            <NavLink
              to="/organization"
              className={({ isActive }) => (isActive ? `${styles.navLink} ${styles.active}` : styles.navLink)}
            >
              Organization
            </NavLink>
          </li>
        </ul>
      </nav>
      <main id="main" ref={mainRef} className={styles.main} tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
