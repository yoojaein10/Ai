import { useState } from "react";
import { Badge, Button, Empty, List, Popover, Spin, Typography } from "antd";
import { BellOutlined, CheckOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import dayjs from "dayjs";
import {
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUnreadCount,
  type Notification,
} from "../api/notifications";

const { Text } = Typography;

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const unreadCountQuery = useUnreadCount();
  const listQuery = useNotifications(20);
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();

  const unread = unreadCountQuery.data?.unread ?? 0;

  const handleClick = (n: Notification) => {
    if (!n.is_read) {
      markRead.mutate(n.id);
    }
    if (n.link) {
      setOpen(false);
      navigate(n.link);
    }
  };

  const content = (
    <div style={{ width: 320 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <Text strong>알림</Text>
        <Button
          type="link"
          size="small"
          icon={<CheckOutlined />}
          disabled={unread === 0 || markAllRead.isPending}
          onClick={() => markAllRead.mutate()}
        >
          모두 읽음
        </Button>
      </div>
      {listQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : !listQuery.data?.items.length ? (
        <Empty description="알림이 없습니다" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          size="small"
          dataSource={listQuery.data.items}
          style={{ maxHeight: 360, overflowY: "auto" }}
          renderItem={(n) => (
            <List.Item
              key={n.id}
              onClick={() => handleClick(n)}
              style={{
                cursor: "pointer",
                background: n.is_read ? undefined : "#e6f4ff",
                padding: "8px 12px",
                borderRadius: 4,
              }}
            >
              <List.Item.Meta
                title={
                  <Text strong={!n.is_read} style={{ fontSize: 13 }}>
                    {n.title}
                  </Text>
                }
                description={
                  <div>
                    {n.message && (
                      <div
                        style={{
                          fontSize: 12,
                          color: "#666",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {n.message}
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: "#999" }}>
                      {dayjs(n.created_at).format("YYYY-MM-DD HH:mm")}
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
    >
      <span style={{ cursor: "pointer", color: "#aaa" }}>
        <Badge count={unread} size="small" offset={[2, -2]}>
          <BellOutlined style={{ color: "#aaa", fontSize: 16 }} />
        </Badge>
      </span>
    </Popover>
  );
}
