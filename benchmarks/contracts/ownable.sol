pragma solidity ^0.8.0;
contract OwnableFixture { address public owner = msg.sender; modifier onlyOwner() { require(msg.sender == owner); _; } function setOwner(address next) external onlyOwner { owner = next; } }
