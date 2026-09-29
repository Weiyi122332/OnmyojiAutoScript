# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import onepush.core
import requests
import yaml
from base64 import b64encode
from onepush import get_notifier
from onepush.core import Provider
from onepush.exceptions import OnePushException
from onepush.providers.custom import Custom
from requests import Response
from smtplib import SMTPResponseException

from module.logger import logger
onepush.core.log = logger


class Notifier:
    def __init__(self, _config: str, enable: bool=False) -> None:
        self.config_name: str = ""
        self.enable: bool = enable

        if not self.enable:
            return
        config = {}
        try:
            for item in yaml.safe_load_all(_config):
                config.update(item)
        except Exception as e:
            logger.error("Fail to load onepush config, skip sending")
            return
        self.config = config
        try:
            # 获取provider
            self.provider_name: str = self.config.pop("provider", None)
            if self.provider_name is None:
                logger.info("No provider specified, skip sending")
                return
            # 获取notifier
            self.notifier: Provider = get_notifier(self.provider_name)
            # 获取notifier的必填参数
            self.required: list[str] = self.notifier.params["required"]
        except OnePushException:
            logger.exception("Init notifier failed")
            return
        except Exception as e:
            logger.exception(e)
            return

    def push(self, **kwargs) -> bool:
        if not self.enable:
            return False
        # 更新配置
        kwargs["title"] = f"{self.config_name} {kwargs['title']}"
        self.config.update(kwargs)
        # pre check
        for key in self.required:
            if key not in self.config:
                logger.warning(
                    f"Notifier {self.notifier} require param '{key}' but not provided"
                )


        if isinstance(self.notifier, Custom):
            if "method" not in self.config or self.config["method"] == "post":
                self.config["datatype"] = "json"
            if not ("data" in self.config or isinstance(self.config["data"], dict)):
                self.config["data"] = {}
            if "title" in kwargs:
                self.config["data"]["title"] = kwargs["title"]
            if "content" in kwargs:
                self.config["data"]["content"] = kwargs["content"]

        if self.provider_name.lower() == "gocqhttp":
            access_token = self.config.get("access_token")
            if access_token:
                self.config["token"] = access_token


        try:
            resp = self.notifier.notify(**self.config)
            if isinstance(resp, Response):
                if resp.status_code != 200:
                    logger.warning("Push notify failed!")
                    logger.warning(f"HTTP Code:{resp.status_code}")
                    return False
                else:
                    if self.provider_name.lower() == "gocqhttp":
                        return_data: dict = resp.json()
                        if return_data["status"] == "failed":
                            logger.warning("Push notify failed!")
                            logger.warning(
                                f"Return message:{return_data['wording']}")
                            return False
        except SMTPResponseException:
            logger.warning("Appear SMTPResponseException")
            pass
        except OnePushException:
            logger.exception("Push notify failed")
            return False
        except Exception as e:
            logger.exception(e)
            return False

        logger.info("Push notify success")
        return True

    def push_image(self, image: bytes, title: str, content: str = '') -> bool:
        return self.push_images([image], title=title, content=content)

    def push_images(self, images: list[bytes], title: str, content: str = '') -> bool:
        """Send one message with all screenshots through go-cqhttp."""
        if not self.enable:
            return False
        if getattr(self, 'provider_name', '').lower() != 'gocqhttp':
            logger.warning('Image notification requires the go-cqhttp provider')
            return False
        if not images:
            return False
        endpoint = self.config.get('endpoint')
        if not endpoint or not (self.config.get('user_id') or self.config.get('group_id')):
            logger.warning('Image notification target is not configured')
            return False
        if any(len(image) > 30 * 1024 * 1024 for image in images):
            logger.warning('Image notification exceeds the go-cqhttp size limit')
            return False

        endpoint = str(endpoint)
        if '://' not in endpoint:
            endpoint = f'http://{endpoint}'
        path = str(self.config.get('path') or '/send_msg')
        url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
        text = f'{self.config_name} {title}'
        if content:
            text = f'{text}\n{content}'
        payload = {
            'message_type': self.config.get('message_type') or (
                'private' if self.config.get('user_id') else 'group'),
            'message': [{'type': 'text', 'data': {'text': text}}] + [
                {'type': 'image', 'data': {'file': f"base64://{b64encode(image).decode('ascii')}"}}
                for image in images
            ],
        }
        for key in ('user_id', 'group_id'):
            if self.config.get(key):
                payload[key] = self.config[key]
        token = self.config.get('access_token') or self.config.get('token')
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            if str(result.get('status', '')).lower() != 'ok':
                logger.warning(f"Image notification failed: status={result.get('status')}")
                return False
        except Exception as exc:
            logger.warning(f'Image notification failed: {exc}')
            return False
        logger.info('Image notification sent')
        return True



