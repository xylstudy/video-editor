import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register } from '../api.js'
import AuthShell from '../components/AuthShell.jsx'
import { Button, Field, InfoBar, TextInput } from '../components/ui.jsx'

export default function Register() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await register(username, password, email)
      navigate('/login')
    } catch (err) {
      setError(err.response?.data?.detail || '注册失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthShell>
      <form onSubmit={handleSubmit} className="vc-auth-form vc-fade-in">
          <span className="vc-auth-form-kicker">GET STARTED</span>
          <h2>创建账号</h2>
          <p>建立你的专属视频创作工作区</p>

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
            <Field label="邮箱" hint="可选，用于找回账号">
              <TextInput
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                autoComplete="email"
              />
            </Field>
            <Field label="密码">
              <TextInput
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="设置密码"
                autoComplete="new-password"
                required
              />
            </Field>
          </div>

          <Button type="submit" loading={loading} size="lg" className="mt-6 w-full">
            注册
          </Button>

          <p className="vc-auth-switch">
            已有账号？{' '}
            <Link to="/login">
              登录
            </Link>
          </p>
        </form>
    </AuthShell>
  )
}
