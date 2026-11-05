# Reverse proxy setup

This guide covers configuring reverse proxies for Starr Studio.

Starr Studio is a FastAPI application that serves its own REST API (`/api/v1/...`) and React single-page frontend. When running behind a reverse proxy, you need to configure path routing (URL base), client IP forwarding (trusted proxies), buffering settings for live logs, and upload size limits for poster images.

## URL base

If you host Studio on a subpath (such as `https://example.com/kometa`), set the **URL base** to `/kometa` in **Settings → General**.

How it works:
- Studio accepts requests with the prefix (`/kometa/...`) and without it (`/...`).
- An internal middleware (`UrlBaseMiddleware`) strips the prefix before passing requests to API routes and page handlers.
- The web page injects `<base href="/kometa/">` into the HTML head so the single-page frontend constructs all API requests, assets, and routes with the base prefix.
- Visiting a page without the prefix automatically redirects to the URL base.
- Because Studio accepts requests with or without the prefix, your reverse proxy can either forward the path as-is or rewrite it.

## Trusted proxies

By default, any request arriving with proxy headers (`X-Forwarded-For`, `Forwarded`, or `X-Real-IP`) is treated as untrusted and will not count as a local address for sign-in. This prevents remote visitors from spoofing proxy headers to bypass authentication.

To let Studio determine the real visitor's IP address:
1. Open **Settings → General**.
2. Under **Trusted proxies**, enter the IP address or CIDR range of your reverse proxy (for example, `127.0.0.1` for a local proxy, or `172.18.0.0/16` for a Docker network).
3. Save changes.

When a request arrives from an address listed in trusted proxies, Studio evaluates the `X-Forwarded-For` chain. It reads the addresses from right to left and selects the right-most address that is not in the trusted proxies list. That address is recorded as the real visitor.

## Buffering and live logs (SSE)

During Kometa runs, Studio streams live console logs to the browser via Server-Sent Events (SSE).

If a reverse proxy buffers response bodies, SSE messages will stall until the proxy buffer fills or the run finishes. Every proxy configuration **must disable response buffering** for Studio routes.

In addition, Kometa runs can take significant time. Ensure your proxy's read timeout is set high enough (for example, 1 hour) so long runs do not disconnect.

## Poster uploads

Studio's collection builder allows uploading custom poster images up to 10 MB in size. Proxies that default to small upload limits (such as Nginx's default 1 MB limit) will reject these uploads with `413 Request Entity Too Large`. Set the proxy's maximum body size to at least 12 MB.

---

## Proxy configurations

All examples below use:
- URL base: `/kometa`
- Studio listening address: `127.0.0.1:8484` (or `starr-studio:8484` in Docker)

### 1. Nginx

A ready-to-use snippet is provided in `deploy/nginx-location.conf`.

Add the following block inside your existing `server { ... }` configuration:

```nginx
location /kometa/ {
    proxy_pass http://127.0.0.1:8484;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;

    # Disable buffering for live Server-Sent Events (SSE) logs
    proxy_buffering off;
    proxy_http_version 1.1;
    proxy_read_timeout 1h;

    # Poster uploads up to 10 MB
    client_max_body_size 12m;
}
```

If your Nginx configuration does not automatically redirect requests without a trailing slash (`/kometa`), add:

```nginx
location = /kometa {
    return 301 $scheme://$host/kometa/;
}
```

### 2. Caddy

In your `Caddyfile`, use `handle_path` to proxy under `/kometa` and set `flush_interval -1` to disable response buffering:

```caddy
example.com {
    handle_path /kometa* {
        reverse_proxy 127.0.0.1:8484 {
            # Disable buffering so Server-Sent Events flush immediately
            flush_interval -1
        }
    }
}
```

Caddy automatically adds `X-Forwarded-For` and `X-Forwarded-Proto` headers and has no default request body limit.

### 3. Traefik

Traefik disables response buffering by default, allowing SSE streams to pass through immediately. It also automatically sets `X-Forwarded-For` and `X-Forwarded-Proto`.

#### Option A: Docker labels

If running both Traefik and Starr Studio in Docker Compose:

```yaml
services:
  starr-studio:
    image: starr-studio:local
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.starr-studio.rule=Host(`example.com`) && PathPrefix(`/kometa`)"
      - "traefik.http.routers.starr-studio.entrypoints=websecure"
      - "traefik.http.routers.starr-studio.tls=true"
      - "traefik.http.services.starr-studio.loadbalancer.server.port=8484"
```

#### Option B: File provider (`dynamic_conf.yml`)

If using Traefik's file provider to point at a non-Docker or standalone Studio instance:

```yaml
http:
  routers:
    starr-studio:
      rule: "Host(`example.com`) && PathPrefix(`/kometa`)"
      entryPoints:
        - "websecure"
      service: "starr-studio"
      tls: {}

  services:
    starr-studio:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8484"
```

To trust the client IP from upstream proxies in Traefik, ensure `forwardedHeaders.trustedIPs` is configured on your entrypoints in Traefik's static configuration.

### 4. SWAG (Secure Web Application Gateway)

SWAG (by LinuxServer.io) provides standard reverse proxy templates. Create a subfolder configuration file at `/config/nginx/proxy-confs/starr-studio.subfolder.conf`:

```nginx
location /kometa {
    return 301 $scheme://$host/kometa/;
}

location ^~ /kometa/ {
    include /config/nginx/proxy.conf;
    include /config/nginx/resolver.conf;

    # Set to 'starr-studio' if in the same Docker network, or '127.0.0.1' if on host
    set $upstream_app 127.0.0.1;
    set $upstream_port 8484;
    set $upstream_proto http;
    proxy_pass $upstream_proto://$upstream_app:$upstream_port;

    # Disable buffering for live Server-Sent Events (SSE) logs
    proxy_buffering off;
    proxy_read_timeout 1h;

    # Poster uploads up to 10 MB
    client_max_body_size 12m;
}
```
