import { Empty, Card } from "antd";

type Props = { title: string };

export default function PlaceholderPage({ title }: Props) {
  return (
    <Card title={title} style={{ minHeight: 400 }}>
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={`${title} — 준비 중입니다.`}
      />
    </Card>
  );
}
