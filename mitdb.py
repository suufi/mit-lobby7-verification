import datetime
import os
import pickle
import random
import string
from typing import List, TypedDict

import discord
import pymongo
import requests
import sendgrid
from dotenv import load_dotenv
from sendgrid.helpers.mail import Content, From, Mail, To

load_dotenv()

mongo_client = pymongo.MongoClient(os.getenv("MONGODB_URI"))
mitdb = mongo_client["mitdb"]

users = mitdb["users"]
verification_codes = mitdb["verification_codes"]
if "created_at_1" not in verification_codes.index_information():
    verification_codes.create_index("created_at", expireAfterSeconds=600)

MIT_PEOPLE_API_URL = "https://mit-people-v3.cloudhub.io/people/v3/people"

sg = sendgrid.SendGridAPIClient(api_key=os.getenv("SENDGRID_API_KEY"))

DepartmentTyping = TypedDict(
    "DepartmentTyping",
    {
        "code": str,
        "name": str,
    },
)

CourseTyping = TypedDict(
    "CourseTyping",
    {
        "departmentCode": str,
        "courseOption": str,
        "name": str,
    },
)

AffiliationTyping = TypedDict(
    "AffiliationTyping",
    {
        "type": str,
        "classYear": str,
        "departments": List[DepartmentTyping],
        "courses": List[CourseTyping],
    },
)

KerbInfoTyping = TypedDict(
    "KerbInfoTyping",
    {
        "kerberosId": str,
        "givenName": str,
        "familyName": str,
        "middleName": str,
        "displayName": str,
        "email": str,
        "phoneNumber": str,
        "website": str,
        "affiliations": List[AffiliationTyping],
        "mitDirectorySuppressed": bool,
    },
)


class MITUserDB:
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            print("configuration", configuration)
            if configuration["logging_channel"]:
                self.logging_channel_id = configuration["logging_channel"]

    def fetch_kerb_info(self, kerb: str) -> KerbInfoTyping | None:
        headers = {
            "Accept": "application/json",
            "client_id": os.getenv("MIT_API_KEY"),
            "client_secret": os.getenv("MIT_API_SECRET"),
        }
        response = requests.get(MIT_PEOPLE_API_URL + "/" + kerb, headers=headers)
        if response.status_code == 404 or response.status_code == 400:
            return None
        return response.json().get("item")

    async def generate_secure_code(self, kerb, discordID):
        # check if blacklisted
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if kerb in configuration["blacklisted_kerbs"]:
                logging_channel = self.bot.get_channel(self.logging_channel_id)
                if isinstance(logging_channel, discord.TextChannel):
                    await logging_channel.send(
                        f":red_circle: Blacklisted kerb ({kerb}) used by <@{discordID}>"
                    )
                return False, "Blacklisted kerb."

        # check if already verified
        if users.find_one({"discordID": discordID}):
            return (
                False,
                "Already verified. Contact an admin if you need to change your kerb.",
            )

        if verification_codes.find_one({"discordID": discordID}):
            logging_channel = self.bot.get_channel(self.logging_channel_id)
            if isinstance(logging_channel, discord.TextChannel):
                await logging_channel.send(
                    f":yellow_circle: Kerb ({kerb}) verification failed to start by <@{discordID}>, too soon warning."
                )
            return (
                False,
                "Already in verification process. Please wait 10 minutes before trying to start a new process.",
            )

        verification_code = "".join(
            random.choice(
                string.ascii_uppercase + string.ascii_lowercase + string.digits
            )
            for _ in range(7)
        )

        code_entry = {
            "kerb": kerb,
            "alum": kerb.endswith("@alum.mit.edu"),
            "discordID": discordID,
            "verification_code": verification_code,
            "created_at": datetime.datetime.utcnow(),
        }

        verification_codes.insert_one(code_entry)

        logging_channel = self.bot.get_channel(self.logging_channel_id)
        if isinstance(logging_channel, discord.TextChannel):
            await logging_channel.send(
                f":white_circle: Kerb ({kerb}) verification started by <@{discordID}>"
            )

        return self.send_code_via_email(kerb, verification_code)

    def send_code_via_email(self, kerb, verification_code):
        from_email = From("mit-discord@mit.edu", "MIT Discord - Lobby 7 Verification")
        if kerb.endswith("@alum.mit.edu"):
            to_email = To(kerb)
        else:
            to_email = To(kerb + "@mit.edu")

        subject = "MIT Discord Verification Code"
        content = Content(
            "text/plain",
            f"Your verification code is: {verification_code}. Please enter /code kerb:{kerb} code:{verification_code} in the #verification channel to complete the verification process. After 10 minutes, this code will expire and you will have to restart the verification process. If you did not request this code, please ignore this email. If you have any questions, feel free to reply back to this email.\n\n- MIT Discord Team",
        )

        mail = Mail(from_email, to_email, subject, content)

        response = sg.client.mail.send.post(request_body=mail.get())  # type: ignore

        if response.status_code == 202:
            return True, None
        else:
            return False, "Could not send email."

    def get_verification_code(self, kerb: str):
        return verification_codes.find_one({"kerb": kerb})

    def get_user(self, kerb: str):
        return (users.find_one({"kerb": kerb}), self.fetch_kerb_info(kerb))

    def get_user_from_discordid(self, discordID: int):
        return users.find_one({"discordID": discordID})

    async def verify_user(
        self, kerb: str, discordID: int, secure_code: str, guildID: int
    ):
        verification_document = self.get_verification_code(kerb)
        if not verification_document:
            return False
        elif (
            verification_document["verification_code"] == secure_code
            and verification_document["discordID"] == discordID
        ):
            # users.update_one({"kerb": kerb}, {"$set": {"verified": True}})
            users.insert_one(
                {
                    "kerb": kerb,
                    "discordID": discordID,
                    "alum": kerb.endswith("@alum.mit.edu"),
                    "verified": True,
                    "verifiedAt": datetime.datetime.now(),
                }
            )
            verification_codes.delete_one({"kerb": kerb})
            logging_channel = self.bot.get_channel(self.logging_channel_id)
            if isinstance(logging_channel, discord.TextChannel):
                await logging_channel.send(
                    f":green_circle: Kerb ({kerb}) verification completed by <@{str(discordID)}>"
                )

            await self.assign_discord_roles(
                guildId=guildID,
                discordId=discordID,
                kerb=kerb,
                alumni=kerb.endswith("@alum.mit.edu"),
            )

            return True
        else:
            return False

    def is_verified(self, kerb: str):
        user, _ = self.get_user(kerb)
        if not user:
            return False
        return user["verified"]

    async def assign_discord_roles(
        self,
        guildId: int,
        discordId: int,
        kerb: str,
        dry_run: bool = False,
        alumni: bool = False,
    ):
        guild = self.bot.get_guild(guildId)
        if not guild:
            return False

        member = guild.get_member(discordId)
        if not member:
            return False

        # check if already verified
        user_data, kerb_data = self.get_user(kerb)
        if not user_data and not dry_run:
            return False

        roles_to_add: List[discord.Role] = []

        if user_data and user_data["verified"]:
            roles_to_add.append(discord.utils.get(guild.roles, name="Verified"))  # type: ignore

        if kerb_data and not alumni:
            xregistered = False
            for affiliation in kerb_data["affiliations"]:
                if affiliation["type"] == "affiliate":
                    roles_to_add.append(discord.utils.get(guild.roles, name="Affiliate"))  # type: ignore

                if "departments" in affiliation.keys():
                    for department in affiliation["departments"]:
                        if department["code"].startswith("NI"):
                            xregistered = True
                        roles_to_add.append(discord.utils.get(guild.roles, name=f"course-{department['code']}"))  # type: ignore

                    if affiliation["type"] == "student":
                        if affiliation["classYear"] == "G":
                            roles_to_add.append(discord.utils.get(guild.roles, name="Grad Student"))  # type: ignore
                        elif xregistered:
                            roles_to_add.append(discord.utils.get(guild.roles, name="X-Reg"))  # type: ignore
                        elif affiliation["classYear"] in ["1", "2", "3", "4"]:
                            roles_to_add.append(discord.utils.get(guild.roles, name="Undergrad"))  # type: ignore

                    elif affiliation["type"] == "staff":
                        roles_to_add.append(discord.utils.get(guild.roles, name="Staff/Faculty"))  # type: ignore
        elif alumni:
            roles_to_add.append(discord.utils.get(guild.roles, name="Alumnus/a"))  # type: ignore

        roles_to_add = [role for role in roles_to_add if role is not None]
        if not dry_run:
            await member.add_roles(*roles_to_add)

        if not dry_run:
            logging_channel = self.bot.get_channel(self.logging_channel_id)
            if isinstance(logging_channel, discord.TextChannel):
                await logging_channel.send(
                    f":green_circle: Assigning {[role.name for role in roles_to_add]} to <@{discordId}>"
                )
        return roles_to_add

        # roles_to_add = []
        # for role in available_roles:
        #     if role.name ==

        # { 'item': {'kerberosId': 'suufi', 'givenName': 'Mohamed', 'familyName': 'Suufi', 'middleName': None, 'displayName': 'Mohamed Suufi', 'email': 'suufi@mit.edu', 'phoneNumber': None, 'website': None, 'affiliations': [{'type': 'student', 'classYear': '2', 'departments': [{'code': '6', 'name': 'Electrical Eng & Computer Sci'}], 'courses': [{'departmentCode': '6', 'courseOption': '7', 'name': 'Computer Science and Molecular Biology (Course 6-7)'}]}], 'mitDirectorySuppressed': False}}

        # for role in available_roles:
        #     if role.name == kerb_data

        # member.add_roles()

    def set_logging_channel(self, channel_id: int):
        # log in pickle file
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            configuration["logging_channel"] = channel_id
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

        self.logging_channel = self.bot.get_channel(channel_id)

    def blacklist_kerb(self, kerb: str):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if kerb not in configuration["blacklisted_kerbs"]:
                configuration["blacklisted_kerbs"].append(kerb)
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

    def unblacklist_kerb(self, kerb: str):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            configuration["blacklisted_kerbs"].remove(kerb)
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

    def get_blacklisted_kerbs(self):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            return configuration["blacklisted_kerbs"]

    def batch_add_toggles(self, roles: List[discord.Role] = [], ids: List[int] = []):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if not "togglable_roles" in configuration.keys():
                configuration["togglable_roles"] = []
            configuration["togglable_roles"].extend([role.id for role in roles])
            configuration["togglable_roles"].extend(ids)
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

    def add_togglable_role(self, role: discord.Role):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if not "togglable_roles" in configuration.keys():
                configuration["togglable_roles"] = []
            if role not in configuration["togglable_roles"]:
                configuration["togglable_roles"].append(role.id)
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

    def remove_togglable_role(self, role: discord.Role):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if not "togglable_roles" in configuration.keys():
                configuration["togglable_roles"] = []
            configuration["togglable_roles"].remove(role.id)
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

    def clear_togglable_roles(self):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if not "togglable_roles" in configuration.keys():
                configuration["togglable_roles"] = []
            configuration["togglable_roles"] = []
        with open("configuration.pkl", "wb") as f:
            pickle.dump(configuration, f)

    def get_togglable_roles(self):
        with open("configuration.pkl", "rb") as f:
            configuration = pickle.load(f)
            if not "togglable_roles" in configuration.keys():
                configuration["togglable_roles"] = []
            return configuration["togglable_roles"]
