from flask import Flask, request, jsonify
import requests, time, os

app = Flask(__name__)

# Loaded from Railway Environment Variables
SUNO_COOKIE = os.getenv("SUNO_COOKIE")

def get_clerk_jwt(cookie):
    """Exchanges the raw cookie for a valid Suno JWT token."""
    headers = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}
    url = "https://clerk.suno.com/v1/client?_clerk_js_version=4.73.4"
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    sessions = data.get('response', {}).get('sessions', [])
    if not sessions:
        raise Exception("Suno Cookie expired or invalid.")
    return sessions[0]['last_active_token']['jwt']

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    lyrics = data.get('lyrics')
    if not lyrics:
        return jsonify({"error": "Missing lyrics"}), 400

    try:
        # 1. Authenticate correctly with Clerk
        jwt_token = get_clerk_jwt(SUNO_COOKIE)
        
        # 2. Fire generation request to Suno WAF
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://suno.com",
            "Referer": "https://suno.com/"
        }
        
        payload = {
            "prompt": lyrics,
            "tags": "cute hindi nursery rhyme, playful cartoon style, 100 bpm, female child singer",
            "title": "Hindi Masti",
            "make_instrumental": False,
            "mv": "chirp-v3-5"
        }

        r = requests.post("https://studio-api.suno.ai/api/generate/v2/", json=payload, headers=headers, timeout=20)
        
        if r.status_code == 503:
            return jsonify({"error": "Cloudflare blocked Railway's IP."}), 503
            
        r.raise_for_status()
        gen_data = r.json()
        clip_id = gen_data.get('clips', [{}])[0].get('id')
        
        if not clip_id:
            return jsonify({"error": "Failed to get clip ID"}), 500

        # 3. Poll for completion
        poll_url = f"https://studio-api.suno.ai/api/feed/?ids={clip_id}"
        for _ in range(35): # ~3 minutes polling
            time.sleep(5)
            poll_r = requests.get(poll_url, headers=headers, timeout=15)
            if poll_r.status_code == 200:
                poll_data = poll_r.json()
                if poll_data and poll_data[0].get('status') == 'complete':
                    return jsonify({"audio_url": poll_data[0].get('audio_url')})
                    
        return jsonify({"error": "Suno rendering timed out."}), 504
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))
