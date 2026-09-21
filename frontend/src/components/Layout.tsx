import { NavLink, Outlet } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/runs', label: 'Evaluation Runs' },
  { to: '/policies', label: 'Policies' },
  { to: '/datasets', label: 'Datasets' },
]

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-title">AI Quality Gate</div>
        <nav>
          <ul>
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => (isActive ? 'nav-link nav-link--active' : 'nav-link')}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  )
}
