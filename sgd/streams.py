def is_semi_valid_title(self, item):
        """
        Lógica Blindada:
        0. Bypass: Se tiver o ID do IMDb no nome, aprova direto.
        1. Títulos Curtos: Exige frase exata ("The Rip" deve aparecer junto).
        2. Títulos Longos: Exige presença das palavras chave (ordem flexível).
        """
        file_name_raw = item.get("sortkeys", {}).get("title", "") or self.item.get("name", "")
        
        # --- 0. BYPASS DA ID DO IMDB ---
        # Se a ID bater com o nome do arquivo, a gente não perde tempo verificando texto.
        imdb_id = getattr(self.strm_meta, "id", None)
        if imdb_id and imdb_id.lower() in file_name_raw.lower():
            return True

        file_clean = re.sub(r"[^a-zA-Z0-9]", " ", file_name_raw).lower()
        file_clean = " ".join(file_clean.split()) # Remove espaços duplos

        match_found = False

        for title in self.strm_meta.titles:
            # Título Esperado Limpo
            title_clean = re.sub(r"[^a-zA-Z0-9]", " ", title).lower()
            
            # --- FIX: Filtra sobras de pontuação de 1 letra (Ex: o 'i' e 'm' de "I'm") ---
            words = [w for w in title_clean.split() if len(w) > 1]
            if not words: # Fallback caso o título original tenha literalmente 1 letra
                words = title_clean.split()
            
            title_clean_filtered = " ".join(words)
            
            # --- CENÁRIO 1: TÍTULO CURTO (Até 2 palavras) ---
            if len(words) <= 2:
                if f" {title_clean_filtered} " in f" {file_clean} ":
                    match_found = True
                    break
                elif title_clean_filtered in file_clean:
                    pattern = r'\b' + re.escape(title_clean_filtered) + r'\b'
                    if re.search(pattern, file_clean):
                        match_found = True
                        break

            # --- CENÁRIO 2: TÍTULO MÉDIO/LONGO (3+ palavras) ---
            else:
                STOP_WORDS = {"and", "of", "to", "in", "for", "on", "at", "by", "with", "the", "a"}
                strong_words = [w for w in words if w not in STOP_WORDS]
                
                if not strong_words: strong_words = words

                file_tokens = set(file_clean.split())
                
                missing = [w for w in strong_words if w not in file_tokens]
                
                if not missing:
                    match_found = True
                    break
                
                if len(strong_words) >= 4 and len(missing) <= 1:
                    match_found = True
                    break

        return match_found
