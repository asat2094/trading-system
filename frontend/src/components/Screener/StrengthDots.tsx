interface Props {
  score: number;  // 1–5
}

export default function StrengthDots({ score }: Props) {
  return (
    <span style={{ letterSpacing: 2 }}>
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} style={{ color: i < score ? "#089981" : "#444" }}>●</span>
      ))}
    </span>
  );
}
