import { Route, HashRouter, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Overview } from './pages/Overview'
import { RunsList } from './pages/RunsList'
import { RunDetail } from './pages/RunDetail'
import { Policies } from './pages/Policies'
import { Datasets } from './pages/Datasets'

function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="runs" element={<RunsList />} />
          <Route path="runs/:runId" element={<RunDetail />} />
          <Route path="policies" element={<Policies />} />
          <Route path="datasets" element={<Datasets />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}

export default App
