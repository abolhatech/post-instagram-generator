from __future__ import annotations

import re
from hashlib import md5

from news_image_generator.models import CopyItem, CopywriterInput, CopywriterOutput


class CopywriterAgent:
    _generic_headlines = [
        "Choque total: ninguém esperava isso",
        "Virada absurda muda tudo agora",
        "Bomba no setor: impacto imediato",
        "Mudança gigante pega mercado de surpresa",
        "Alerta máximo: cenário virou completamente",
        "Reviravolta forte abala o mercado hoje",
    ]

    _keyword_groups = [
        (
            ["ia", "ai", "openai", "startup", "chip", "modelo"],
            [
                "IA dá virada e surpreende geral",
                "Setor de IA entra em choque",
                "Mudança na IA acelera disputa global",
                "Nova jogada em IA abala gigantes",
            ],
        ),
        (
            ["mercado", "ações", "bolsa", "economia", "finance"],
            [
                "Mercado reage e cenário vira rápido",
                "Economia muda e investidores entram em alerta",
                "Sinal forte no mercado assusta analistas",
                "Virada econômica surpreende todo o setor",
            ],
        ),
        (
            ["governo", "eleição", "política", "guerra", "conflito"],
            [
                "Tensão cresce e decisão surpreende país",
                "Conflito escala e cenário vira",
                "Decisão política gera choque imediato",
                "Novo movimento muda o jogo político",
            ],
        ),
    ]

    def run(self, payload: CopywriterInput) -> CopywriterOutput:
        results: list[CopyItem] = []
        for article in payload.articles:
            headline = self._build_headline(article.title, article.summary, article.id)
            results.append(
                CopyItem(
                    id=article.id,
                    title=article.title,
                    viralHeadline=headline,
                    angle="alto impacto emocional",
                )
            )
        return CopywriterOutput(copies=results)

    def _build_headline(self, title: str, summary: str, article_id: str) -> str:
        seed_text = f"{title} {summary}".lower()
        selected_pool = self._generic_headlines
        for keywords, options in self._keyword_groups:
            if any(keyword in seed_text for keyword in keywords):
                selected_pool = options
                break

        idx = int(md5(article_id.encode("utf-8")).hexdigest(), 16) % len(selected_pool)
        candidate = selected_pool[idx]
        cleaned = self._normalize(candidate)
        return self._limit_words(cleaned, 8).upper()

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _limit_words(text: str, max_words: int) -> str:
        words = text.split(" ")
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words])
