import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login } from '../api.js'
import { useAuth } from '../context/auth-context.js'
import AuthShell from '../components/AuthShell.jsx'
import { Button, Field, InfoBar, TextInput } from '../components/ui.jsx'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login: doLogin } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(username, password)
      doLogin(res.data.access_token, res.data.user)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || '登录失败，请检查用户名和密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthShell>
      <form onSubmit={handleSubmit} className="vc-auth-form vc-fade-in">
          <span className="vc-auth-form-kicker">WELCOME BACK</span>
          <h2>欢迎回来</h2>
          <p>登录后继续你的视频创作工作流</p>

          {error && (
            <div className="mb-4">
              <InfoBar type="error">{error}</InfoBar>
            </div>
          )}

          <div className="space-y-4">
            <Field label="用户名">
              <TextInput
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="输入用户名"
                autoComplete="username"
                required
              />
            </Field>
            <Field label="密码">
              <TextInput
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入密码"
                autoComplete="current-password"
                required
              />
            </Field>
          </div>

          <Button type="submit" loading={loading} size="lg" className="mt-6 w-full">
            登录
          </Button>

          <p className="vc-auth-switch">
            还没有账号？{' '}
            <Link to="/register">
              注册
            </Link>
          </p>
        </form>
    </AuthShell>
  )
}
