def _strip_www(domain: str) -> str:
    try:
        return domain[4:] if domain.lower().startswith('www.') else domain
    except Exception:
        return domain


def _base_domain(domain: str) -> str:
    try:
        parts = [p for p in domain.split('.') if p]
        if len(parts) <= 2:
            return domain
        if len(parts[-1]) == 2 and len(parts[-2]) <= 3:
            return '.'.join(parts[-3:])
        return '.'.join(parts[-2:])
    except Exception:
        return domain


def _domain_variants(domain: str):
    try:
        d = _strip_www(domain)
        base = _base_domain(d)
        variants = [d]
        if base != d:
            variants.append(base)
        www_base = f"www.{base}"
        if www_base not in variants:
            variants.append(www_base)
        return variants
    except Exception:
        return [domain]
