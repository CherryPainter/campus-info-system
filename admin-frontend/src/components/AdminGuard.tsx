import { Navigate } from "react-router-dom";
import { useUser } from "@/contexts/UserContext";
import { Spin, Card } from "antd";

export default function AdminGuard({ children }: { children: React.ReactNode }) {
  const { loading, isAdmin } = useUser();

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          height: "100vh",
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  if (!isAdmin) {
    return <Navigate to="/weather" replace />;
  }

  return <>{children}</>;
}
