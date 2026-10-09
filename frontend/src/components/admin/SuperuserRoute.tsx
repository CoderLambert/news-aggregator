import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ShieldAlert } from 'lucide-react'
import AuthModal from '@/components/AuthModal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/context/AuthContext'

export default function SuperuserRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  if (loading) return <LoadingSpinner />

  if (!user) {
    return (
      <>
        <div className="mx-auto flex min-h-[65vh] max-w-xl items-center px-4 py-12">
          <Card className="w-full">
            <CardHeader>
              <CardTitle>需要超级管理员登录</CardTitle>
              <CardDescription>登录成功后将继续打开 {location.pathname}。</CardDescription>
            </CardHeader>
          </Card>
        </div>
        <AuthModal allowRegister={false} loginTitle="管理员登录" onClose={() => navigate('/', { replace: true })} onSuccess={() => undefined} />
      </>
    )
  }

  if (!user.isSuperuser) {
    return (
      <div className="mx-auto flex min-h-[65vh] max-w-xl items-center px-4 py-12">
        <Card className="w-full">
          <CardHeader>
            <div className="mb-2 flex size-11 items-center justify-center rounded-full bg-red-50 text-red-600">
              <ShieldAlert aria-hidden="true" />
            </div>
            <CardTitle>无权访问管理控制台</CardTitle>
            <CardDescription>该区域只向已激活的超级管理员开放。公开注册不会自动获得管理权限，请联系部署者授权。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild><Link to="/">返回新闻首页</Link></Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return children
}
