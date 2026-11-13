import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export function ProjectProgressChart({ data }: { data: { name: string; Progress: number }[] }) {
  return (
    <ResponsiveContainer height={300} width="100%">
      <BarChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" fontSize={11} tickLine={false} />
        <YAxis domain={[0, 100]} fontSize={11} tickLine={false} unit="%" />
        <Tooltip />
        <Bar dataKey="Progress" fill="#0f766e" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function MaterialUsageChart({
  data
}: {
  data: { name: string; Issued: number; Consumed: number }[];
}) {
  return (
    <ResponsiveContainer height={300} width="100%">
      <BarChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" fontSize={11} tickLine={false} />
        <YAxis fontSize={11} tickLine={false} />
        <Tooltip />
        <Bar dataKey="Issued" fill="#0f766e" radius={[4, 4, 0, 0]} />
        <Bar dataKey="Consumed" fill="#f59e0b" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
