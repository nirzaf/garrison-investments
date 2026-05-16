"use client";

import { useEffect, useMemo, useState } from "react";
import { Bell, ChevronRight, LogOut, Menu, Moon, Play, Rocket, Search, Sun } from "lucide-react";

import { navItems, productTourSteps, projects, type PortalNavGroup, type ScreenKey } from "@/lib/portal-data";
import { screenTitles } from "@/components/screen-titles";
import { ProductTourOverlay, getTourModalPosition, type TourModalPosition, type TourRect } from "@/components/tour-overlay";
import { FeatureGuideCard, OverviewScreen } from "@/components/screens/overview";
import { AccountsScreen, AdminScreen, ApprovalsScreen, AuthScreen, DashboardScreen, DeliveryScreen, DocumentsScreen, MaterialsScreen, MobileScreen, NotificationsScreen, PhotosScreen, ProjectsScreen, ReportsScreen, SecurityScreen } from "@/components/screens/module-screens";

const navGroups: { group: PortalNavGroup; label: string }[] = [
  { group: "core", label: "Core Flow" },
  { group: "management", label: "Management" },
  { group: "phase2", label: "Phase 2" },
  { group: "delivery", label: "Delivery" },
];

export function PortalPrototype() {
  const [activeScreen, setActiveScreen] = useState<ScreenKey>("overview");
  const [selectedProject, setSelectedProject] = useState(projects[0]);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(true);
  const [tourIndex, setTourIndex] = useState(0);
  const [tourRect, setTourRect] = useState<TourRect | null>(null);
  const [tourModalPosition, setTourModalPosition] = useState<TourModalPosition | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  const activeNav = useMemo(
    () => navItems.find((item) => item.key === activeScreen),
    [activeScreen],
  );

  const activeTourStep = productTourSteps[tourIndex];

  useEffect(() => {
    const stored = window.localStorage.getItem("garrisons-theme");
    const resolved = stored === "light" ? "light" : "dark";
    setTheme(resolved);
    document.documentElement.setAttribute("data-theme", resolved);
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    window.localStorage.setItem("garrisons-theme", next);
    document.documentElement.setAttribute("data-theme", next);
  };

  const selectScreen = (screen: ScreenKey) => {
    setActiveScreen(screen);
    setMobileNavOpen(false);
  };

  const startTour = () => {
    setTourOpen(true);
    setTourIndex(0);
    selectScreen(productTourSteps[0].screen);
  };

  const goToTourStep = (nextIndex: number) => {
    const boundedIndex = (nextIndex + productTourSteps.length) % productTourSteps.length;
    setTourIndex(boundedIndex);
    selectScreen(productTourSteps[boundedIndex].screen);
    setTourOpen(true);
  };

  useEffect(() => {
    const handleTourControl = (event: PointerEvent | MouseEvent) => {
      if (event.type === "click" && "detail" in event && event.detail > 0) {
        return;
      }

      if (!(event.target instanceof Element)) {
        return;
      }

      const control = event.target.closest<HTMLElement>("[data-tour-action]");
      if (!control) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      const action = control.dataset.tourAction;
      if (action === "next") {
        goToTourStep(tourIndex + 1);
      }
      if (action === "prev") {
        goToTourStep(tourIndex - 1);
      }
      if (action === "close") {
        setTourOpen(false);
      }
      if (action === "step" && control.dataset.tourStep) {
        goToTourStep(Number(control.dataset.tourStep));
      }
    };

    document.addEventListener("pointerdown", handleTourControl, true);
    document.addEventListener("mousedown", handleTourControl, true);
    document.addEventListener("click", handleTourControl, true);

    return () => {
      document.removeEventListener("pointerdown", handleTourControl, true);
      document.removeEventListener("mousedown", handleTourControl, true);
      document.removeEventListener("click", handleTourControl, true);
    };
  }, [tourIndex]);

  useEffect(() => {
    if (!tourOpen) {
      setTourRect(null);
      setTourModalPosition(null);
      return;
    }

    let frameId = 0;
    let timeoutId = 0;

    const updateTourTarget = (shouldScroll = false) => {
      const target = document.querySelector<HTMLElement>(
        `[data-tour-target="${activeTourStep.target}"]`,
      );

      if (!target) {
        setTourRect(null);
        setTourModalPosition(null);
        return;
      }

      if (shouldScroll) {
        target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      }

      timeoutId = window.setTimeout(() => {
        const rect = target.getBoundingClientRect();
        const padding = 8;
        const nextRect = {
          top: Math.max(rect.top - padding, 8),
          left: Math.max(rect.left - padding, 8),
          width: Math.min(rect.width + padding * 2, window.innerWidth - 16),
          height: Math.min(rect.height + padding * 2, window.innerHeight - 16),
        };

        setTourRect(nextRect);
        setTourModalPosition(getTourModalPosition(nextRect, activeTourStep.position));
      }, 220);
    };

    const handleResize = () => updateTourTarget(false);
    const handleScroll = () => updateTourTarget(false);

    frameId = window.requestAnimationFrame(() => updateTourTarget(true));
    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.clearTimeout(timeoutId);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [activeTourStep, activeScreen, tourOpen]);

  return (
    <main className="appShell">
      <aside className={`sideRail ${mobileNavOpen ? "isOpen" : ""}`} aria-label="Prototype modules">
        <div className="brandBlock">
          <img className="brandIcon" src="/brand/logo-mark.png" alt="" />
          <div>
            <strong>Garrisons</strong>
            <span>Internal Portal</span>
          </div>
        </div>

        <nav className="moduleNav">
          {navGroups.map(({ group, label }) => (
            <section className="moduleGroup" key={group}>
              <h2>{label}</h2>
              {navItems
                .filter((item) => item.group === group)
                .map((item) => (
                  <button
                    className={[
                      item.key === activeScreen ? "isActive" : "",
                      tourOpen && item.key === activeTourStep.screen ? "isTourTarget" : "",
                    ].join(" ")}
                    key={item.key}
                    onClick={() => selectScreen(item.key)}
                    type="button"
                  >
                    <item.icon size={17} />
                    <span>{item.label}</span>
                    <small>{item.phase}</small>
                  </button>
                ))}
            </section>
          ))}
        </nav>

        <div className="prototypeStatus">
          <span>Coverage</span>
          <strong>All documented modules</strong>
          <p>Interactive dummy data for stakeholder walkthroughs.</p>
        </div>
      </aside>

      <section className="workspace">
        <header className="topBar">
          <button
            aria-label="Toggle module navigation"
            className="mobileMenu"
            onClick={() => setMobileNavOpen((value) => !value)}
            type="button"
          >
            <Menu size={20} />
          </button>
          <div>
            <span className="breadcrumb">
              Prototype <ChevronRight size={14} /> {activeNav?.phase}
            </span>
            <h1>{screenTitles[activeScreen]}</h1>
          </div>
          <div className="topActions">
            <div className="searchBox">
              <Search size={16} />
              <span>Search reports, docs, inventory</span>
            </div>
            <button
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              onClick={toggleTheme}
              type="button"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button data-tour-target="notification-bell" type="button">
              <Bell size={16} />
              17
            </button>
            <button className="tourButton" onClick={startTour} type="button">
              <Play size={16} />
              Walkthrough
            </button>
            <button type="button">
              <LogOut size={16} />
            </button>
          </div>
        </header>

        {tourOpen ? (
          <ProductTourOverlay
            activeStep={activeTourStep}
            index={tourIndex}
            modalPosition={tourModalPosition}
            onClose={() => setTourOpen(false)}
            onNext={() => goToTourStep(tourIndex + 1)}
            onPrev={() => goToTourStep(tourIndex - 1)}
            onStep={goToTourStep}
            targetRect={tourRect}
          />
        ) : (
          <button className="floatingTourButton" onClick={startTour} type="button">
            <Rocket size={17} />
            Guided walkthrough
          </button>
        )}

        <section className="screenCard" key={activeScreen}>
          {activeScreen !== "overview" ? <FeatureGuideCard screen={activeScreen} /> : null}
          {activeScreen === "overview" ? <OverviewScreen onOpen={selectScreen} onStartTour={startTour} /> : null}
          {activeScreen === "auth" ? <AuthScreen /> : null}
          {activeScreen === "dashboard" ? <DashboardScreen /> : null}
          {activeScreen === "projects" ? (
            <ProjectsScreen selectedProject={selectedProject} setSelectedProject={setSelectedProject} />
          ) : null}
          {activeScreen === "reports" ? <ReportsScreen /> : null}
          {activeScreen === "approvals" ? <ApprovalsScreen /> : null}
          {activeScreen === "materials" ? <MaterialsScreen /> : null}
          {activeScreen === "documents" ? <DocumentsScreen /> : null}
          {activeScreen === "photos" ? <PhotosScreen /> : null}
          {activeScreen === "accounts" ? <AccountsScreen /> : null}
          {activeScreen === "notifications" ? <NotificationsScreen /> : null}
          {activeScreen === "admin" ? <AdminScreen /> : null}
          {activeScreen === "mobile" ? <MobileScreen /> : null}
          {activeScreen === "security" ? <SecurityScreen /> : null}
          {activeScreen === "delivery" ? <DeliveryScreen /> : null}
        </section>
      </section>
    </main>
  );
}
