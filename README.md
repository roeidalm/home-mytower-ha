# MyTower Home Assistant Integration

Custom component for [MyTower](https://app.my-tower.co.il) building management system.

## Features

- 🚗 **Gate buttons** — open entry/exit parking gates (dynamically discovered)
- 📨 **Unread messages** sensor
- 💳 **Monthly fee** sensor (₪)
- 📅 **Paid months** sensor

## Installation

1. Copy `custom_components/mytower/` to your HA `custom_components/` folder
2. Restart Home Assistant
3. Go to **Settings → Integrations → Add Integration → MyTower**
4. Enter your phone number → receive SMS → enter OTP

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.mytower_unread_messages` | sensor | Unread messages count |
| `sensor.mytower_monthly_fee` | sensor | Monthly building fee (₪) |
| `sensor.mytower_paid_months` | sensor | Months paid this year |
| `button.mytower_שער_כניסה` | button | Open entry gate |
| `button.mytower_שער_יציאה` | button | Open exit gate |

Gates are **dynamically discovered** at setup — works for any building using MyTower.

## Requirements

- Home Assistant 2023.1+
- Active MyTower account
- Israeli phone number registered in MyTower

## Notes

- Authentication is SMS OTP based (phone number + 6-digit code)
- Session token is stored securely in HA config entry
- Token expiry triggers automatic re-authentication flow
- Mobile User-Agent is required (server rejects desktop UA)
