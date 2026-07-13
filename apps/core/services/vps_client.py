"""VPS client — calls the upload API on a VPS endpoint."""
import requests


def upload_to_vps(vps, profile_name, video_url):
    """
    Call the upload API on a VPS endpoint.

    Args:
        vps: VPS model instance with api_endpoint and optional api_key.
        profile_name: The TikTok profile name to upload to.
        video_url: The URL of the YouTube video to upload.

    Returns:
        tuple[bool, str]: (success, error_message).
            success=True and error_message="" on success.
            success=False and error_message=<reason> on failure.
    """
    try:
        headers = {"Content-Type": "application/json"}
        if vps.api_key:
            headers["Authorization"] = f"Bearer {vps.api_key}"

        response = requests.post(
            f"{vps.api_endpoint}/api/upload-profile",
            json={"profile_name": profile_name, "video_url": video_url},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return True, ""
    except requests.Timeout:
        return False, f"Timeout connecting to VPS {vps.name}"
    except requests.ConnectionError:
        return False, f"Connection error to VPS {vps.name} ({vps.api_endpoint})"
    except requests.HTTPError as e:
        # Include detailed response body from VPS to ease debugging
        resp_details = ""
        try:
            resp_details = f" | Details: {response.text}"
        except Exception:
            pass
        return False, f"HTTP {response.status_code} from VPS {vps.name}: {e}{resp_details}"
    except requests.RequestException as e:
        return False, f"Request failed to VPS {vps.name}: {e}"
