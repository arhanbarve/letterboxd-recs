import { useState } from "react";

const FACE = "https://image.tmdb.org/t/p/w185";
const POSTER = "https://image.tmdb.org/t/p/w154";

export default function PersonCard({ person }) {
  const [open, setOpen] = useState(false);
  const films = person.top_films || [];
  return (
    <div className="person-face" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
         onClick={() => setOpen((o) => !o)}>
      {person.profile_path ? <img src={FACE + person.profile_path} alt={person.name} />
        : <div className="person-face-placeholder">{person.name[0]}</div>}
      <div className="person-name">{person.name}</div>
      {open && films.length > 0 && (
        <div className="person-popover" role="dialog" aria-label={`Top films with ${person.name}`}>
          {films.map((f) => (
            <div className="person-pop-film" key={f.title}>
              {f.poster_path && <img src={POSTER + f.poster_path} alt={f.title} />}
              <div className="person-pop-meta"><b>{f.title}</b><span>{f.rating}★</span></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
