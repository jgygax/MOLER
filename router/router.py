import requests
import base64
import os
import json
from dotenv import load_dotenv
import time

load_dotenv()


class Router:
    def __init__(
        self,
        username,
        password,
        host="192.168.0.1",
        user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
        silent=False,
    ):
        self.username = username
        self.password = password
        self.host = host
        self.silent = silent
        self.base_url = f"http://{host}"
        self.headers = {
            "User-Agent": user_agent,
            "Referer": self.base_url,
            "Origin": self.base_url,
        }
        self.session = requests.Session()
        self.is_logged_in = False
        self.account_power = "0"
        self.csrf_token = ""

    def request(self, method, path, data=None, params=None, **kwargs):
        """Generic wrapper for requests that adds user agent and session management."""
        url = f"{self.base_url}{path}"
        # Include CSRF token in headers if we have it
        headers = self.headers.copy()
        if self.csrf_token:
            headers["CSRFToken"] = self.csrf_token

        try:
            response = self.session.request(
                method=method,
                url=url,
                data=data,
                params=params,
                headers=headers,
                **kwargs,
            )
            return response
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            # The router sometimes returns malformed status lines (e.g. "}")
            # or terminates connections early even if the command was processed.
            if not self.silent:
                print(
                    f"Warning: Connection error during {path} (expected for some commands): {e}"
                )
            # Return a mock response object to avoid crashing
            mock_resp = requests.Response()
            mock_resp.status_code = 200
            mock_resp._content = b'{"result": "failure_but_sent"}'
            return mock_resp

    def set_cmd(self, goform_id, data=None):
        """Generic endpoint for /goform/goform_set_cmd_process"""
        data = data or {}
        payload = {"isTest": data.get("isTest", "false"), "goformId": goform_id}
        # Merge other data into payload
        for k, v in data.items():
            if k not in ["isTest", "goformId"]:
                payload[k] = v

        # Add CSRF token if we have it and it's not explicitly provided
        if self.csrf_token and "CSRFToken" not in payload:
            payload["CSRFToken"] = self.csrf_token

        return self.request("POST", "/goform/goform_set_cmd_process", data=payload)

    def get_cmd(self, cmd, data=None):
        """Generic endpoint for /goform/goform_get_cmd_process using POST"""
        data = data or {}
        payload = {"isTest": data.get("isTest", "false"), "cmd": cmd}
        # Merge other data into payload
        for k, v in data.items():
            if k not in ["isTest", "cmd"]:
                payload[k] = v

        # Add CSRF token if we have it
        if self.csrf_token and "CSRFToken" not in payload:
            payload["CSRFToken"] = self.csrf_token

        return self.request("POST", "/goform/goform_get_cmd_process", data=payload)

    def network_tools(self, url, subcmd="0", ping_times=1, port="-1"):
        """
        Send ping or traceroute command to router using /goform/goform_get_cmd_process
        subcmd '0' for ping, '1' for traceroute
        """
        data = {
            "pingTimes": str(ping_times),
            "url": url,
            "subcmd": subcmd,
            "port": str(port),
        }
        return self.get_cmd("network_tools", data)

    def get_status(self):
        """
        Fetch multiple status values at once using multi_data=1
        """
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            status_commands = config.get("status_commands", [])
        except Exception as e:
            print(f"Error loading config.json: {e}")
            return {}

        data = {"multi_data": "1", "cmd": ",".join(status_commands)}

        response = self.get_cmd(data["cmd"], data)

        try:
            return {k: v for k, v in response.json().items() if v}
        except Exception:
            return {}

    def get_ping_results(self, subcmd="0"):
        """Get results from router based on subcmd (0 for ping, 1 for trace)"""
        filename = "ping.html" if subcmd == "0" else "trace.html"
        try:
            response = self.request("GET", f"/data/{filename}", timeout=10)
            return response.text.strip()
        except Exception as e:
            print(f"Error getting results from {filename}: {e}")
            return None

    def get_traceroute_results(self):
        """Helper to get traceroute results specifically"""
        return self.get_ping_results(subcmd="1")

    def get_token(self):
        """Fetch CSRF/Auth token if required by router"""
        response = self.get_cmd("get_token")
        try:
            data = response.json()
            self.csrf_token = data.get("token", self.csrf_token)
            return data
        except Exception:
            return {}

    def get_device_version(self):
        """Fetch device hardware and software version info"""
        response = self.get_cmd("device_version")
        try:
            return response.json()
        except Exception:
            return {}

    def reboot(self):
        """Reboot the router"""
        return self.set_cmd("REBOOT_DEVICE")

    def connect(self):
        """Trigger WAN connection"""
        return self.set_cmd("CONNECT_NETWORK")

    def disconnect(self):
        """Trigger WAN disconnection"""
        return self.set_cmd("DISCONNECT_NETWORK")

    def get_station_list(self):
        """List currently attached WiFi devices"""
        response = self.get_cmd("station_list")
        try:
            return response.json().get("station_list", [])
        except Exception:
            return []

    def get_lan_station_list(self):
        """List currently attached LAN (cable) devices"""
        response = self.get_cmd("lan_station_list")
        try:
            return response.json().get("lan_station_list", [])
        except Exception:
            return []

    def get_sms_ready(self):
        """
        Check if SMS module is ready and initialize if needed.
        Corresponds to JS getSMSReady.
        """
        data = {"cmd": "sms_cmd_status_info", "sms_cmd": "1"}
        response = self.get_cmd("sms_cmd_status_info", data)
        try:
            return response.json()
        except Exception:
            return {}

    def get_sms_messages(
        self, page=0, count=500, mem_store=None, tags=None, order_by="order by id desc"
    ):
        """
        Fetch SMS messages.
        Corresponds to JS getSMSMessages.
        """
        data = {
            "cmd": "sms_data_total",
            "page": str(page),
            "data_per_page": str(count),
            "order_by": order_by,
        }
        if mem_store:
            data["mem_store"] = str(mem_store)
        if tags:
            data["tags"] = str(tags)

        response = self.get_cmd("sms_data_total", data)
        try:
            return response.json()
        except Exception:
            return {"messages": []}

    # Alias for backward compatibility if needed, using the new method
    def get_sms_list(self, page=0, count=20):
        return self.get_sms_messages(page, count)

    def send_sms(self, number, message, sms_id="-1"):
        """
        Send an SMS.
        Corresponds to JS sendSMS.
        """
        # Encode message
        # Note: JS uses `escapeMessage(encodeMessage(e.message))`.
        # For GSM7_default, some routers expect plain text (url-encoded by transport), others hex.
        # Original router.py used plain text. We will revert to plain text for ASCII.

        is_ascii = True
        try:
            # Check for non-GSM-7 compatible chars roughly
            message.encode("ascii")
        except UnicodeEncodeError:
            is_ascii = False

        if is_ascii:
            # Use plain text for GSM7 default
            encoded_body = message
            encode_type = "GSM7_default"
        else:
            # UTF-16BE Hex Uppercase for Unicode
            encoded_body = message.encode("utf-16-be").hex().upper()
            encode_type = "UNICODE"

        import datetime

        now = datetime.datetime.now().strftime("%y;%m;%d;%H;%M;%S;+1")

        data = {
            "goformId": "SEND_SMS",
            "notCallback": "true",
            "Number": number,
            "sms_time": now,
            "MessageBody": encoded_body,
            "ID": sms_id,
            "encode_type": encode_type,
        }
        return self.set_cmd("SEND_SMS", data)

    def save_sms(self, number, message, index="-1", group_id=""):
        """
        Save an SMS draft.
        Corresponds to JS saveSMS.
        """
        is_ascii = True
        try:
            message.encode("ascii")
        except UnicodeEncodeError:
            is_ascii = False

        if is_ascii:
            encoded_body = message
            encode_type = "GSM7_default"
        else:
            encoded_body = message.encode("utf-16-be").hex().upper()
            encode_type = "UNICODE"

        import datetime

        now = datetime.datetime.now().strftime("%y;%m;%d;%H;%M;%S;+1")

        # JS uses SMSNumber: e.numbers.join(";") + ";"
        # If number is a list, join it. Else assume string.
        if isinstance(number, list):
            sms_number = ";".join(number) + ";"
        else:
            sms_number = number + ";"

        data = {
            "goformId": "SAVE_SMS",
            "notCallback": "true",
            "SMSMessage": encoded_body,
            "SMSNumber": sms_number,
            "Index": index,
            "encode_type": encode_type,
            "sms_time": now,
            "draft_group_id": group_id,
        }
        return self.set_cmd("SAVE_SMS", data)

    def delete_all_messages(self, location):
        """
        Delete all messages in a location.
        Corresponds to JS deleteAllMessages.
        """
        data = {
            "goformId": "ALL_DELETE_SMS",
            "notCallback": "true",
            "which_cgi": location,
        }
        # The JS does a status check loop after this (sms_cmd_status_info).
        # We perform the delete action here. The user might need to poll get_sms_ready or similar.
        return self.set_cmd("ALL_DELETE_SMS", data)

    def delete_message(self, sms_ids):
        """
        Delete specific messages.
        Corresponds to JS deleteMessage.
        """
        if isinstance(sms_ids, list):
            msg_id = ";".join(map(str, sms_ids)) + ";"
        else:
            msg_id = str(sms_ids) + ";"

        data = {"goformId": "DELETE_SMS", "notCallback": "true", "msg_id": msg_id}
        return self.set_cmd("DELETE_SMS", data)

    # Backward compatibility alias
    def delete_sms(self, sms_ids):
        return self.delete_message(sms_ids)

    def set_sms_read(self, sms_ids):
        """
        Mark messages as read.
        Corresponds to JS setSmsRead.
        """
        if isinstance(sms_ids, list):
            msg_id = ";".join(map(str, sms_ids))
            if len(sms_ids) > 0:
                msg_id += ";"
        else:
            msg_id = str(sms_ids) + ";"

        data = {"goformId": "SET_MSG_READ", "msg_id": msg_id, "tag": "0"}
        return self.set_cmd("SET_MSG_READ", data)

    def get_sms_delivery_report(self, page=0, count=500):
        """
        Get SMS delivery reports.
        Corresponds to JS getSMSDeliveryReport.
        """
        data = {
            "cmd": "sms_status_rpt_data",
            "page": str(page),
            "data_per_page": str(count),
        }
        response = self.get_cmd("sms_status_rpt_data", data)
        try:
            return response.json()
        except Exception:
            return {}

    def get_sms_capability(self):
        """
        Get SMS storage capability/usage info.
        Corresponds to JS getSmsCapability.
        """
        data = {"cmd": "sms_capacity_info"}
        response = self.get_cmd("sms_capacity_info", data)
        try:
            return response.json()
        except Exception:
            return {}

    def send_ussd(self, ussd_code):
        """Send a USSD command (e.g. *100#)"""
        return self.set_cmd(
            "USSD_PROCESS",
            {"USSD_operator": "ussd_send", "USSD_send_number": ussd_code},
        )

    def get_wifi_basic(self):
        """Get basic WiFi settings (SSID, AuthMode, etc.)"""
        cmds = "wifi_cur_state,wifiEnabled,SSID1,AuthMode,HideSSID,MAX_Access_num,EncrypType"
        response = self.get_cmd(cmds, {"multi_data": "1"})
        try:
            return response.json()
        except Exception:
            return {}

    def scan_networks(self):
        """Trigger a manual network scan"""
        self.set_cmd("SCAN_NETWORK")
        # Note: result is usually fetched later via get_cmd(m_netselect_contents)
        return {"status": "scan_triggered"}

    def set_network_mode(self, mode):
        """Set network mode (e.g. '0' for Auto, '1' for 3G Only, '2' for 4G Only)"""
        return self.set_cmd("SET_NETWORK", {"BearerPreference": mode})

    def get_login_data(self):
        """Imitates getLoginData: V"""
        response = self.request(
            "GET",
            "/goform/goform_get_cmd_process",
            params={"multi_data": "1", "cmd": "login_data"},
        )
        try:
            data = response.json()
            self.csrf_token = data.get("CSRFToken", "")
            return data
        except Exception:
            return {}

    def login(self):
        """Imitates JS login logic"""
        self.get_login_data()

        encoded_user = base64.b64encode(self.username.encode()).decode()
        encoded_pass = base64.b64encode(self.password.encode()).decode()

        data = {"username": encoded_user, "password": encoded_pass}

        response = self.set_cmd("LOGIN", data)

        try:
            res_json = response.json()
            result = res_json.get("result")
            if result in ["0", "4"]:
                self.is_logged_in = True
                self.account_power = res_json.get("power", "0")
                return {"result": True, "power": self.account_power}
            else:
                self.is_logged_in = False
                error_map = {
                    "1": "Login Fail",
                    "2": "duplicateUser",
                    "3": "badPassword",
                    "5": "notexistUser",
                }
                return {
                    "result": False,
                    "errorType": error_map.get(result, "Login Fail"),
                }
        except Exception as e:
            return {"result": False, "errorType": "Login Fail", "exception": str(e)}

    def logout(self):
        """Imitates logout function"""
        response = self.set_cmd("LOGOUT")
        try:
            if response.json().get("result") == "success":
                self.is_logged_in = False
                self.account_power = "0"
                return {"result": True}
        except Exception:
            pass
        return {"result": False, "errorType": "loggedOutError"}


if __name__ == "__main__":
    username = os.getenv("ROUTER_USERNAME", "admin")
    password = os.getenv("ROUTER_PASSWORD")
    pin = os.getenv("ROUTER_SIM_PIN")
    host = os.getenv("ROUTER_HOST", "192.168.0.1")

    while True:

        try:
            router = Router(username, password, host=host)
            login_res = router.login()

            if login_res.get("result"):
                print(f"Login Successful! Power Level: {router.account_power}")

                response = router.set_cmd(
                    "ENTER_PIN", {"isTest": "false", "PinNumber": pin}
                )

                if response.json().get("result") == "success":
                    break

        except Exception as e:
            print(e)

        time.sleep(10)

    print("Logged in, pin unlocked")